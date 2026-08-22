use std::path::PathBuf;
use std::sync::atomic::Ordering;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use crossbeam_channel::{Receiver, Sender, bounded};
use serde::{Deserialize, Serialize};

use crate::ai::{AiEvent, AiWorker, AiWorkerConfig};
#[cfg(windows)]
use crate::audio::windows::WindowsAudioBackend;
use crate::audio::{AudioCaptureBackend, DeviceSelection};
use crate::normalizer::AudioNormalizer;
use crate::subtitle::{SubtitleAssembler, SubtitleUpdate, TranscriptHypothesis};

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AppStatus {
    #[default]
    Starting,
    LoadingModel,
    InitializingGpu,
    ConnectingAudio,
    Listening,
    SpeechDetected,
    Transcribing,
    Translating,
    Paused,
    NoAudio,
    Error,
    Stopped,
}

impl AppStatus {
    pub fn label(self) -> &'static str {
        match self {
            Self::Starting => "Starting",
            Self::LoadingModel => "Loading model",
            Self::InitializingGpu => "Initializing GPU",
            Self::ConnectingAudio => "Connecting audio",
            Self::Listening => "Listening",
            Self::SpeechDetected => "Speech detected",
            Self::Transcribing => "Transcribing",
            Self::Translating => "Translating",
            Self::Paused => "Paused",
            Self::NoAudio => "No system audio",
            Self::Error => "Error",
            Self::Stopped => "Stopped",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AudioActivity {
    #[default]
    None,
    Audio,
    Speech,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Diagnostics {
    pub status: AppStatus,
    pub input_device: String,
    pub sample_rate: u32,
    pub channels: u16,
    pub audio_peak: f32,
    pub audio_rms: f32,
    pub audio_activity: AudioActivity,
    pub vad_state: String,
    pub detected_language: String,
    pub language_candidate: String,
    pub language_confidence: f32,
    pub language_stable: bool,
    pub inference_task: String,
    pub asr_engine: String,
    pub translation_engine: String,
    pub audio_duration_ms: Option<u64>,
    pub inference_duration_ms: Option<u64>,
    pub real_time_factor: Option<f32>,
    pub avg_logprob: Option<f32>,
    pub no_speech_probability: Option<f32>,
    pub compression_ratio: Option<f32>,
    pub quality_passed: Option<bool>,
    pub quality_issue_count: usize,
    pub translation_memory_hit: bool,
    pub verification_inference_duration_ms: Option<u64>,
    pub verification_attempted: bool,
    pub verification_selected: bool,
    pub asr_latency_ms: Option<u64>,
    pub translation_latency_ms: Option<u64>,
    pub total_latency_ms: Option<u64>,
    pub capture_queue_depth: usize,
    pub capture_queue_capacity: usize,
    pub model: String,
    pub inference_backend: String,
    pub gpu: String,
    pub captured_frames: u64,
    pub dropped_frames: u64,
    pub dropped_ai_chunks: u64,
    pub dropped_worker_audio_chunks: u64,
    pub dropped_worker_events: u64,
    pub coalesced_asr_jobs: u64,
    pub recoveries: u64,
}

#[derive(Clone, Debug)]
pub struct RuntimeConfig {
    pub python: PathBuf,
    pub worker_script: PathBuf,
    pub model_dir: PathBuf,
    pub preset: String,
    pub model: Option<String>,
    pub inference_device: String,
    pub compute_type: String,
    pub audio_device: DeviceSelection,
    pub allow_model_download: bool,
}

impl RuntimeConfig {
    pub fn from_environment() -> Self {
        let application_root = application_root();
        let packaged_python = application_root.join("python/python.exe");
        let python = std::env::var_os("LIVESUB_PYTHON")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                if packaged_python.is_file() {
                    packaged_python
                } else {
                    application_root.join(".venv/Scripts/python.exe")
                }
            });
        Self {
            python,
            worker_script: std::env::var_os("LIVESUB_WORKER")
                .map(PathBuf::from)
                .unwrap_or_else(|| application_root.join("ai_worker/worker.py")),
            model_dir: std::env::var_os("LIVESUB_MODEL_DIR")
                .map(PathBuf::from)
                .unwrap_or_else(|| application_root.join("models")),
            preset: std::env::var("LIVESUB_PRESET").unwrap_or_else(|_| "balanced".to_owned()),
            model: std::env::var("LIVESUB_MODEL").ok(),
            inference_device: std::env::var("LIVESUB_DEVICE").unwrap_or_else(|_| "auto".to_owned()),
            compute_type: std::env::var("LIVESUB_COMPUTE_TYPE")
                .unwrap_or_else(|_| "auto".to_owned()),
            audio_device: DeviceSelection::Auto,
            allow_model_download: false,
        }
    }
}

/// Resolve colocated release assets without making development builds depend
/// on the shell's working directory. Packaged builds place the worker next to
/// the executable; repository builds fall back to the repository root.
pub fn application_root() -> PathBuf {
    if let Ok(executable) = std::env::current_exe()
        && let Some(parent) = executable.parent()
        && parent.join("ai_worker/worker.py").is_file()
    {
        return parent.to_path_buf();
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

#[derive(Clone, Debug)]
pub enum RuntimeEvent {
    Status(AppStatus),
    Subtitle(SubtitleUpdate),
    Diagnostics(Box<Diagnostics>),
    Error(String),
}

enum RuntimeCommand {
    Stop,
}

pub struct RuntimeHandle {
    commands: Sender<RuntimeCommand>,
    events: Receiver<RuntimeEvent>,
    thread: Option<JoinHandle<()>>,
}

impl RuntimeHandle {
    pub fn start(config: RuntimeConfig) -> anyhow::Result<Self> {
        let (command_sender, command_receiver) = bounded(2);
        let (event_sender, event_receiver) = bounded(128);
        let thread = thread::Builder::new()
            .name("livesub-runtime".into())
            .spawn(move || {
                if let Err(error) = run_pipeline(config, command_receiver, &event_sender) {
                    let _ = event_sender.try_send(RuntimeEvent::Status(AppStatus::Error));
                    let _ = event_sender.try_send(RuntimeEvent::Error(format!("{error:#}")));
                }
            })?;
        Ok(Self {
            commands: command_sender,
            events: event_receiver,
            thread: Some(thread),
        })
    }

    pub fn events(&self) -> &Receiver<RuntimeEvent> {
        &self.events
    }

    /// Requests shutdown without waiting for an in-flight inference to finish.
    /// Desktop callers use this path so the UI thread never blocks on ASR.
    pub fn request_stop(&self) {
        let _ = self.commands.try_send(RuntimeCommand::Stop);
    }

    pub fn is_finished(&self) -> bool {
        self.thread
            .as_ref()
            .is_none_or(std::thread::JoinHandle::is_finished)
    }

    pub fn stop(&mut self) {
        self.request_stop();
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

impl Drop for RuntimeHandle {
    fn drop(&mut self) {
        self.stop();
    }
}

fn emit(sender: &Sender<RuntimeEvent>, event: RuntimeEvent) {
    let priority = match &event {
        RuntimeEvent::Error(_) | RuntimeEvent::Status(AppStatus::Error | AppStatus::Stopped) => {
            true
        }
        RuntimeEvent::Subtitle(SubtitleUpdate::Upsert { segment }) => segment.is_final,
        _ => false,
    };
    let sent = match sender.try_send(event) {
        Ok(()) => true,
        Err(crossbeam_channel::TrySendError::Full(event)) if priority => sender
            .send_timeout(event, Duration::from_millis(250))
            .is_ok(),
        Err(_) => false,
    };
    if !sent {
        tracing::warn!("desktop event queue full; dropping stale runtime event");
    }
}

fn unix_time_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn hypothesis_from_event(event: &AiEvent) -> Option<TranscriptHypothesis> {
    Some(TranscriptHypothesis {
        segment_id: event.segment_id?,
        revision: event.revision.unwrap_or_default(),
        text: event.text.clone().unwrap_or_default(),
        source_text: event.source_text.clone(),
        source_language: event
            .source_language
            .clone()
            .unwrap_or_else(|| "unknown".into()),
        language_confidence: event.language_confidence.unwrap_or_default(),
        is_final: event.is_final.unwrap_or(false),
        audio_start_ms: event.audio_start_ms.unwrap_or_default(),
        audio_end_ms: event.audio_end_ms.unwrap_or_default(),
        asr_started_ms: event.asr_started_ms,
        asr_completed_ms: event.asr_completed_ms,
        confidence: event.avg_logprob,
        suppressed: event.suppressed.unwrap_or(false),
        end_to_end_latency_ms: event
            .audio_capture_end_unix_ms
            .map(|audio_end| unix_time_ms().saturating_sub(audio_end)),
    })
}

fn handle_ai_event(
    event: AiEvent,
    assembler: &mut SubtitleAssembler,
    diagnostics: &mut Diagnostics,
    subtitle_deadline: &mut Option<Instant>,
    sender: &Sender<RuntimeEvent>,
) {
    match event.kind.as_str() {
        "status" => match event.state.as_deref() {
            Some("starting") => emit(sender, RuntimeEvent::Status(AppStatus::Starting)),
            Some("loading_model") => {
                diagnostics.status = AppStatus::LoadingModel;
                diagnostics.model = event
                    .model
                    .clone()
                    .unwrap_or_else(|| diagnostics.model.clone());
                diagnostics.inference_backend = backend_label(&event);
                emit(sender, RuntimeEvent::Status(AppStatus::LoadingModel));
            }
            Some("initializing_gpu") => {
                diagnostics.status = AppStatus::InitializingGpu;
                diagnostics.model = event
                    .model
                    .clone()
                    .unwrap_or_else(|| diagnostics.model.clone());
                diagnostics.inference_backend = backend_label(&event);
                emit(sender, RuntimeEvent::Status(AppStatus::InitializingGpu));
            }
            Some("listening") => {
                diagnostics.status = AppStatus::Listening;
                diagnostics.model = event
                    .model
                    .clone()
                    .unwrap_or_else(|| diagnostics.model.clone());
                diagnostics.inference_backend = backend_label(&event);
                diagnostics.gpu = match event.cuda_devices {
                    Some(count) if count > 0 => format!("{count} CUDA device(s) available"),
                    Some(_) => "No CUDA device".into(),
                    None => diagnostics.gpu.clone(),
                };
                emit(sender, RuntimeEvent::Status(AppStatus::Listening));
            }
            Some("transcribing") => {
                diagnostics.status = AppStatus::Transcribing;
                emit(sender, RuntimeEvent::Status(AppStatus::Transcribing));
            }
            Some("translating") => {
                diagnostics.status = AppStatus::Translating;
                emit(sender, RuntimeEvent::Status(AppStatus::Translating));
            }
            _ => {}
        },
        "vad" => {
            diagnostics.vad_state = event.state.clone().unwrap_or_default();
            match event.state.as_deref() {
                Some("speech_started") => {
                    diagnostics.audio_activity = AudioActivity::Speech;
                    diagnostics.status = AppStatus::SpeechDetected;
                    emit(sender, RuntimeEvent::Status(AppStatus::SpeechDetected));
                }
                Some("speech_ended") => {
                    diagnostics.audio_activity = AudioActivity::Audio;
                    diagnostics.status = AppStatus::Listening;
                    emit(sender, RuntimeEvent::Status(AppStatus::Listening));
                }
                _ => {}
            }
        }
        "transcript" => {
            if let Some(hypothesis) = hypothesis_from_event(&event) {
                diagnostics.language_candidate = hypothesis.source_language.clone();
                diagnostics.language_confidence = hypothesis.language_confidence;
                diagnostics.language_stable = event.language_stable.unwrap_or(false);
                if event.language_stable.unwrap_or(false) {
                    diagnostics.detected_language = hypothesis.source_language.clone();
                    diagnostics.language_confidence = hypothesis.language_confidence;
                }
                diagnostics.inference_task = event.inference_task.clone().unwrap_or_default();
                diagnostics.asr_engine = event.asr_engine.clone().unwrap_or_default();
                diagnostics.translation_engine =
                    event.translation_engine.clone().unwrap_or_default();
                diagnostics.audio_duration_ms = event.audio_duration_ms;
                diagnostics.inference_duration_ms = event.inference_duration_ms;
                diagnostics.real_time_factor = event.real_time_factor;
                diagnostics.avg_logprob = event.avg_logprob;
                diagnostics.no_speech_probability = event.no_speech_probability;
                diagnostics.compression_ratio = event.compression_ratio;
                diagnostics.quality_passed = event.quality_passed;
                diagnostics.quality_issue_count = event.quality_issues.len();
                diagnostics.translation_memory_hit = event.translation_memory_hit.unwrap_or(false);
                diagnostics.verification_inference_duration_ms =
                    event.verification_inference_duration_ms;
                diagnostics.verification_attempted = event.verification_attempted.unwrap_or(false);
                diagnostics.verification_selected = event.verification_selected.unwrap_or(false);
                diagnostics.inference_backend = event
                    .backend
                    .clone()
                    .unwrap_or_else(|| diagnostics.inference_backend.clone());
                diagnostics.asr_latency_ms = hypothesis
                    .asr_started_ms
                    .zip(hypothesis.asr_completed_ms)
                    .map(|(start, end)| end.saturating_sub(start));
                diagnostics.translation_latency_ms =
                    event.translation_inference_duration_ms.or(Some(0));
                diagnostics.total_latency_ms = hypothesis.end_to_end_latency_ms;
                let is_final = hypothesis.is_final;
                if let Some(update) = assembler.apply(hypothesis) {
                    emit(sender, RuntimeEvent::Subtitle(update));
                }
                if is_final {
                    *subtitle_deadline = Some(Instant::now() + Duration::from_secs(4));
                }
            }
        }
        "language" => {
            if event.state.as_deref() == Some("reset") {
                diagnostics.detected_language.clear();
                diagnostics.language_candidate.clear();
                diagnostics.language_confidence = 0.0;
                diagnostics.language_stable = false;
            }
        }
        "warning" => {
            if event.code.as_deref() == Some("model_backend_failed") {
                emit(
                    sender,
                    RuntimeEvent::Error(format!(
                        "{} backend unavailable; trying fallback: {}",
                        event.backend.unwrap_or_default(),
                        event.message.unwrap_or_default()
                    )),
                );
            }
        }
        "metric" => match event.name.as_deref() {
            Some("audio_chunks_dropped") => {
                diagnostics.dropped_worker_audio_chunks = event.value.unwrap_or_else(|| {
                    diagnostics
                        .dropped_worker_audio_chunks
                        .saturating_add(event.delta.unwrap_or(1))
                });
            }
            Some("asr_jobs_dropped") => {
                diagnostics.coalesced_asr_jobs = diagnostics
                    .coalesced_asr_jobs
                    .saturating_add(event.delta.unwrap_or(1));
            }
            _ => {}
        },
        "error" => emit(
            sender,
            RuntimeEvent::Error(event.message.unwrap_or_else(|| "AI worker error".into())),
        ),
        _ => {}
    }
}

fn backend_label(event: &AiEvent) -> String {
    match (&event.backend, &event.compute_type) {
        (Some(backend), Some(compute_type)) => format!("{backend}/{compute_type}"),
        (Some(backend), None) => backend.clone(),
        _ => String::new(),
    }
}

#[cfg(windows)]
fn run_pipeline(
    config: RuntimeConfig,
    commands: Receiver<RuntimeCommand>,
    events: &Sender<RuntimeEvent>,
) -> anyhow::Result<()> {
    const CAPTURE_QUEUE_CAPACITY: usize = 16;
    emit(events, RuntimeEvent::Status(AppStatus::Starting));
    let backend = WindowsAudioBackend;
    let devices = backend.enumerate_devices()?;
    let input_device = match &config.audio_device {
        DeviceSelection::Auto => devices
            .iter()
            .find(|device| device.is_default)
            .map(|device| device.name.clone())
            .unwrap_or_else(|| "System default".into()),
        DeviceSelection::Id(id) | DeviceSelection::Microphone(id) => devices
            .iter()
            .find(|device| &device.id == id)
            .map(|device| device.name.clone())
            .unwrap_or_else(|| id.clone()),
    };

    let ai_config = AiWorkerConfig {
        python: config.python,
        script: config.worker_script,
        model_dir: config.model_dir,
        preset: config.preset.clone(),
        model: config.model.clone(),
        device: config.inference_device,
        compute_type: config.compute_type,
        source_language: None,
        allow_model_download: config.allow_model_download,
    };
    let worker = AiWorker::start(ai_config)?;
    let worker_events = worker.events().clone();
    let mut diagnostics = Diagnostics {
        status: AppStatus::Starting,
        input_device,
        capture_queue_capacity: CAPTURE_QUEUE_CAPACITY,
        model: config.model.unwrap_or(config.preset),
        gpu: "AUTO".into(),
        ..Diagnostics::default()
    };
    let mut assembler = SubtitleAssembler::default();
    let mut subtitle_deadline = None;

    // Do not capture speech before the persistent model has completed its
    // smoke decodes. This prevents startup audio from filling/coalescing the
    // two-slot inference queue and makes "Listening" a truthful ready state.
    loop {
        if commands.try_recv().is_ok() {
            worker.stop()?;
            emit(events, RuntimeEvent::Status(AppStatus::Stopped));
            return Ok(());
        }
        match worker_events.recv_timeout(Duration::from_millis(100)) {
            Ok(event) => {
                let ready = event.kind == "status" && event.state.as_deref() == Some("listening");
                let fatal =
                    event.kind == "error" && event.code.as_deref() == Some("model_load_failed");
                let fatal_message = event.message.clone();
                handle_ai_event(
                    event,
                    &mut assembler,
                    &mut diagnostics,
                    &mut subtitle_deadline,
                    events,
                );
                if fatal {
                    worker.stop()?;
                    anyhow::bail!(
                        "AI model could not start: {}",
                        fatal_message.unwrap_or_else(|| "unknown worker failure".into())
                    );
                }
                if ready {
                    break;
                }
            }
            Err(crossbeam_channel::RecvTimeoutError::Timeout) => {}
            Err(crossbeam_channel::RecvTimeoutError::Disconnected) => {
                anyhow::bail!("AI worker stopped before becoming ready");
            }
        }
    }

    diagnostics.status = AppStatus::ConnectingAudio;
    emit(events, RuntimeEvent::Status(AppStatus::ConnectingAudio));
    let (audio_sender, audio_receiver) = bounded(CAPTURE_QUEUE_CAPACITY);
    let capture = backend.start(config.audio_device, audio_sender)?;
    let capture_metrics = capture.metrics.clone();
    diagnostics.status = AppStatus::Listening;
    emit(events, RuntimeEvent::Status(AppStatus::Listening));
    let mut normalizer = None;
    let mut normalized_buffer = Vec::<f32>::with_capacity(3_200);
    let mut audio_sequence = 0_u64;
    let mut next_metrics = Instant::now();
    let mut last_nonzero_audio = None;
    let mut stopping = false;

    while !stopping {
        if commands.try_recv().is_ok() {
            stopping = true;
            continue;
        }
        if let Ok(frame) = audio_receiver.recv_timeout(Duration::from_millis(10)) {
            diagnostics.sample_rate = frame.sample_rate;
            diagnostics.channels = frame.channels;
            diagnostics.audio_peak = frame.peak();
            diagnostics.audio_rms = frame.rms();
            if diagnostics.audio_peak > 0.000_01 {
                last_nonzero_audio = Some(Instant::now());
                if diagnostics.audio_activity != AudioActivity::Speech {
                    diagnostics.audio_activity = AudioActivity::Audio;
                }
            }
            let normalizer = match normalizer.as_mut() {
                Some(normalizer) => normalizer,
                None => normalizer.insert(AudioNormalizer::new(frame.sample_rate, frame.channels)?),
            };
            normalized_buffer.extend(normalizer.normalize(&frame)?);
            while normalized_buffer.len() >= 1_600 {
                let remainder = normalized_buffer.split_off(1_600);
                let chunk = std::mem::replace(&mut normalized_buffer, remainder);
                worker.try_send_audio(audio_sequence, &chunk);
                audio_sequence = audio_sequence.wrapping_add(1);
            }
        }
        for event in worker_events.try_iter() {
            handle_ai_event(
                event,
                &mut assembler,
                &mut diagnostics,
                &mut subtitle_deadline,
                events,
            );
        }
        if subtitle_deadline.is_some_and(|deadline| Instant::now() >= deadline) {
            if let Some(current) = assembler.current() {
                emit(
                    events,
                    RuntimeEvent::Subtitle(SubtitleUpdate::Clear {
                        segment_id: current.id,
                    }),
                );
            }
            subtitle_deadline = None;
        }
        if Instant::now() >= next_metrics {
            diagnostics.capture_queue_depth = audio_receiver.len();
            diagnostics.captured_frames = capture_metrics.frames.load(Ordering::Relaxed);
            diagnostics.dropped_frames = capture_metrics.dropped_frames.load(Ordering::Relaxed);
            diagnostics.recoveries = capture_metrics.recoveries.load(Ordering::Relaxed);
            diagnostics.dropped_ai_chunks =
                worker.metrics.audio_chunks_dropped.load(Ordering::Relaxed);
            diagnostics.dropped_worker_events = worker.metrics.event_drops.load(Ordering::Relaxed);
            if diagnostics.audio_activity != AudioActivity::Speech
                && last_nonzero_audio.is_none_or(|last| last.elapsed() > Duration::from_secs(2))
            {
                diagnostics.audio_activity = AudioActivity::None;
                if matches!(
                    diagnostics.status,
                    AppStatus::Listening | AppStatus::NoAudio
                ) {
                    diagnostics.status = AppStatus::NoAudio;
                    emit(events, RuntimeEvent::Status(AppStatus::NoAudio));
                }
            }
            emit(
                events,
                RuntimeEvent::Diagnostics(Box::new(diagnostics.clone())),
            );
            next_metrics = Instant::now() + Duration::from_secs(1);
        }
    }

    capture.stop()?;
    if !normalized_buffer.is_empty() {
        worker.try_send_audio(audio_sequence, &normalized_buffer);
    }
    worker.stop()?;
    emit(events, RuntimeEvent::Status(AppStatus::Stopped));
    Ok(())
}

#[cfg(not(windows))]
fn run_pipeline(
    _config: RuntimeConfig,
    _commands: Receiver<RuntimeCommand>,
    _events: &Sender<RuntimeEvent>,
) -> anyhow::Result<()> {
    anyhow::bail!("the initial LiveSub runtime requires Windows")
}
