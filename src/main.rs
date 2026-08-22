use std::time::{Duration, Instant};

use anyhow::Context;
use crossbeam_channel::bounded;
use livesub::ai::{AiEvent, AiWorker, AiWorkerConfig};
use livesub::audio::{AudioCaptureBackend, DeviceSelection};
use livesub::normalizer::AudioNormalizer;
use livesub::runtime::RuntimeConfig;
use livesub::subtitle::{SubtitleAssembler, TranscriptHypothesis};
use serde::Serialize;

#[cfg(windows)]
use livesub::audio::windows::WindowsAudioBackend;

#[derive(Serialize)]
struct ProbeReport {
    elapsed_ms: u128,
    native_frames: u64,
    native_samples: u64,
    normalized_samples: u64,
    normalized_duration_ms: u64,
    peak: f32,
    rms: f32,
    non_silent_packets: u64,
    queue_capacity: usize,
    queue_max_depth: usize,
    capture: livesub::audio::CaptureMetricsSnapshot,
}

fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "livesub=info".into()),
        )
        .with_target(false)
        .init();

    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("list-audio") => list_audio(),
        Some("probe-audio") => {
            let seconds = args
                .windows(2)
                .find(|pair| pair[0] == "--seconds")
                .and_then(|pair| pair[1].parse::<u64>().ok())
                .unwrap_or(10);
            probe_audio(Duration::from_secs(seconds))
        }
        Some("run-live") => run_live(&args[2..]),
        Some("desktop") => {
            let start_immediately = args[2..].iter().any(|argument| argument == "--start");
            livesub::desktop::run(start_immediately)
                .map_err(|error| anyhow::anyhow!(error.to_string()))
        }
        _ => {
            println!("LiveSub development commands:");
            println!("  livesub list-audio");
            println!("  livesub probe-audio --seconds 10");
            println!("  livesub run-live --python .venv\\Scripts\\python.exe --model base");
            println!("  livesub desktop [--start]");
            Ok(())
        }
    }
}

fn argument_value<'a>(arguments: &'a [String], name: &str) -> Option<&'a str> {
    arguments
        .windows(2)
        .find(|pair| pair[0] == name)
        .map(|pair| pair[1].as_str())
}

fn handle_ai_event(event: AiEvent, assembler: &mut SubtitleAssembler) {
    if event.kind != "transcript" {
        println!("AI {}", serde_json::to_string(&event).unwrap_or_default());
        return;
    }
    println!(
        "AI_TRANSCRIPT {}",
        serde_json::to_string(&event).unwrap_or_default()
    );
    let Some(segment_id) = event.segment_id else {
        return;
    };
    let hypothesis = TranscriptHypothesis {
        segment_id,
        revision: event.revision.unwrap_or_default(),
        text: event.text.unwrap_or_default(),
        source_text: event.source_text,
        source_language: event.source_language.unwrap_or_else(|| "unknown".into()),
        language_confidence: event.language_confidence.unwrap_or_default(),
        is_final: event.is_final.unwrap_or(false),
        audio_start_ms: event.audio_start_ms.unwrap_or_default(),
        audio_end_ms: event.audio_end_ms.unwrap_or_default(),
        asr_started_ms: event.asr_started_ms,
        asr_completed_ms: event.asr_completed_ms,
        confidence: None,
        suppressed: event.suppressed.unwrap_or(false),
        end_to_end_latency_ms: event.audio_capture_end_unix_ms.map(|audio_end| {
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis()
                .saturating_sub(u128::from(audio_end)) as u64
        }),
    };
    if let Some(update) = assembler.apply(hypothesis) {
        println!(
            "SUBTITLE {}",
            serde_json::to_string(&update).unwrap_or_default()
        );
    }
}

#[cfg(windows)]
fn run_live(arguments: &[String]) -> anyhow::Result<()> {
    use std::path::PathBuf;
    use std::sync::atomic::Ordering;

    let seconds = argument_value(arguments, "--seconds")
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(30);
    let environment = RuntimeConfig::from_environment();
    let python = argument_value(arguments, "--python")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("LIVESUB_PYTHON").map(PathBuf::from))
        .unwrap_or(environment.python);
    let mut worker_config = AiWorkerConfig::development(python);
    worker_config.script = environment.worker_script;
    worker_config.model = argument_value(arguments, "--model").map(str::to_owned);
    worker_config.preset = argument_value(arguments, "--preset")
        .unwrap_or("balanced")
        .to_owned();
    worker_config.device = argument_value(arguments, "--device")
        .unwrap_or("auto")
        .to_owned();
    worker_config.compute_type = argument_value(arguments, "--compute-type")
        .unwrap_or("auto")
        .to_owned();
    worker_config.model_dir = argument_value(arguments, "--model-dir")
        .map(PathBuf::from)
        .unwrap_or(environment.model_dir);
    worker_config.allow_model_download = arguments
        .iter()
        .any(|argument| argument == "--allow-model-download");

    let worker = AiWorker::start(worker_config)?;
    let event_receiver = worker.events().clone();
    let mut assembler = SubtitleAssembler::default();
    loop {
        let event = event_receiver
            .recv_timeout(Duration::from_secs(30))
            .context("AI worker did not report startup progress")?;
        let ready = event.kind == "status" && event.state.as_deref() == Some("listening");
        let fatal = event.kind == "error" && event.code.as_deref() == Some("model_load_failed");
        handle_ai_event(event, &mut assembler);
        anyhow::ensure!(!fatal, "AI worker could not load the model");
        if ready {
            break;
        }
    }
    let backend = WindowsAudioBackend;
    let (audio_sender, audio_receiver) = bounded(16);
    let capture = backend.start(DeviceSelection::Auto, audio_sender)?;
    let capture_metrics = capture.metrics.clone();
    let deadline = Instant::now() + Duration::from_secs(seconds);
    let mut normalizer = None;
    let mut normalized_buffer = Vec::<f32>::with_capacity(3_200);
    let mut audio_sequence = 0_u64;

    while Instant::now() < deadline {
        if let Ok(frame) = audio_receiver.recv_timeout(Duration::from_millis(10)) {
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
        for event in event_receiver.try_iter() {
            handle_ai_event(event, &mut assembler);
        }
    }
    capture.stop()?;
    if !normalized_buffer.is_empty() {
        worker.try_send_audio(audio_sequence, &normalized_buffer);
    }
    let sent = worker.metrics.audio_chunks_sent.load(Ordering::Relaxed);
    let dropped = worker.metrics.audio_chunks_dropped.load(Ordering::Relaxed);
    worker.stop()?;
    for event in event_receiver.try_iter() {
        handle_ai_event(event, &mut assembler);
    }
    println!(
        "PIPELINE capture={} capture_dropped={} ai_chunks={} ai_dropped={} finals={}",
        capture_metrics.frames.load(Ordering::Relaxed),
        capture_metrics.dropped_frames.load(Ordering::Relaxed),
        sent,
        dropped,
        assembler.history().len()
    );
    Ok(())
}

#[cfg(not(windows))]
fn run_live(_arguments: &[String]) -> anyhow::Result<()> {
    anyhow::bail!("the first LiveSub pipeline requires Windows")
}

#[cfg(windows)]
fn list_audio() -> anyhow::Result<()> {
    let backend = WindowsAudioBackend;
    let devices = backend.enumerate_devices()?;
    println!("{}", serde_json::to_string_pretty(&devices)?);
    Ok(())
}

#[cfg(not(windows))]
fn list_audio() -> anyhow::Result<()> {
    anyhow::bail!("the first LiveSub capture backend requires Windows")
}

#[cfg(windows)]
fn probe_audio(duration: Duration) -> anyhow::Result<()> {
    const QUEUE_CAPACITY: usize = 8;
    let backend = WindowsAudioBackend;
    let (sender, receiver) = bounded(QUEUE_CAPACITY);
    let handle = backend.start(DeviceSelection::Auto, sender)?;
    let metrics = handle.metrics.clone();
    let started = Instant::now();
    let deadline = started + duration;
    let mut normalizer = None;
    let mut native_frames = 0_u64;
    let mut native_samples = 0_u64;
    let mut normalized_samples = 0_u64;
    let mut squared_sum = 0.0_f64;
    let mut peak = 0.0_f32;
    let mut non_silent_packets = 0_u64;
    let mut queue_max_depth = 0_usize;

    while Instant::now() < deadline {
        let remaining = deadline.saturating_duration_since(Instant::now());
        let frame = match receiver.recv_timeout(remaining.min(Duration::from_millis(250))) {
            Ok(frame) => frame,
            Err(crossbeam_channel::RecvTimeoutError::Timeout) => continue,
            Err(error) => return Err(error).context("WASAPI frame channel disconnected"),
        };
        queue_max_depth = queue_max_depth.max(receiver.len());
        native_frames += 1;
        native_samples += frame.samples.len() as u64;
        if frame.peak() > 0.000_01 {
            non_silent_packets += 1;
        }
        let normalizer = match normalizer.as_mut() {
            Some(normalizer) => normalizer,
            None => normalizer.insert(AudioNormalizer::new(frame.sample_rate, frame.channels)?),
        };
        let samples = normalizer.normalize(&frame)?;
        for sample in samples {
            peak = peak.max(sample.abs());
            squared_sum += f64::from(sample) * f64::from(sample);
            normalized_samples += 1;
        }
    }
    handle.stop()?;

    let report = ProbeReport {
        elapsed_ms: started.elapsed().as_millis(),
        native_frames,
        native_samples,
        normalized_samples,
        normalized_duration_ms: normalized_samples * 1_000 / 16_000,
        peak,
        rms: if normalized_samples == 0 {
            0.0
        } else {
            (squared_sum / normalized_samples as f64).sqrt() as f32
        },
        non_silent_packets,
        queue_capacity: QUEUE_CAPACITY,
        queue_max_depth,
        capture: metrics.snapshot(),
    };
    println!("{}", serde_json::to_string_pretty(&report)?);
    anyhow::ensure!(report.native_frames > 0, "WASAPI returned no audio packets");
    Ok(())
}

#[cfg(not(windows))]
fn probe_audio(_duration: Duration) -> anyhow::Result<()> {
    anyhow::bail!("the first LiveSub capture backend requires Windows")
}
