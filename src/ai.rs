use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStderr, Command, Stdio};
use std::sync::{
    Arc,
    atomic::{AtomicU64, Ordering},
};
use std::thread::{self, JoinHandle};
use std::time::Duration;

use anyhow::Context;
use base64::Engine;
use crossbeam_channel::{Receiver, Sender, bounded};
use serde::{Deserialize, Serialize};

use crate::INTERNAL_SAMPLE_RATE;

pub const AI_PROTOCOL_VERSION: u16 = 1;

#[derive(Clone, Debug, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum AiCommand {
    Configure {
        protocol: u16,
        preset: String,
        model: Option<String>,
        device: String,
        compute_type: String,
        model_dir: String,
        source_language: Option<String>,
        allow_model_download: bool,
    },
    Audio {
        protocol: u16,
        sequence: u64,
        sample_rate: u32,
        capture_end_unix_ms: u64,
        pcm_s16le: String,
    },
    Ping {
        protocol: u16,
        request_id: u64,
    },
    Shutdown {
        protocol: u16,
    },
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct AiEvent {
    #[serde(rename = "type")]
    pub kind: String,
    #[serde(default)]
    pub state: Option<String>,
    #[serde(default)]
    pub code: Option<String>,
    #[serde(default)]
    pub message: Option<String>,
    #[serde(default)]
    pub segment_id: Option<u64>,
    #[serde(default)]
    pub revision: Option<u64>,
    #[serde(default)]
    pub text: Option<String>,
    #[serde(default)]
    pub source_text: Option<String>,
    #[serde(default)]
    pub source_language: Option<String>,
    #[serde(default)]
    pub language_confidence: Option<f32>,
    #[serde(default)]
    pub language_stable: Option<bool>,
    #[serde(default)]
    pub is_partial: Option<bool>,
    #[serde(default)]
    pub is_final: Option<bool>,
    #[serde(default)]
    pub audio_start_ms: Option<u64>,
    #[serde(default)]
    pub audio_end_ms: Option<u64>,
    #[serde(default)]
    pub audio_capture_end_unix_ms: Option<u64>,
    #[serde(default)]
    pub asr_started_ms: Option<u64>,
    #[serde(default)]
    pub asr_completed_ms: Option<u64>,
    #[serde(default)]
    pub emitted_ms: Option<u64>,
    #[serde(default)]
    pub backend: Option<String>,
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default)]
    pub compute_type: Option<String>,
    #[serde(default)]
    pub cuda_devices: Option<u64>,
    #[serde(default)]
    pub inference_task: Option<String>,
    #[serde(default)]
    pub asr_engine: Option<String>,
    #[serde(default)]
    pub translation_engine: Option<String>,
    #[serde(default)]
    pub audio_duration_ms: Option<u64>,
    #[serde(default)]
    pub inference_duration_ms: Option<u64>,
    #[serde(default)]
    pub source_inference_duration_ms: Option<u64>,
    #[serde(default)]
    pub translation_inference_duration_ms: Option<u64>,
    #[serde(default)]
    pub real_time_factor: Option<f32>,
    #[serde(default)]
    pub suppressed: Option<bool>,
    #[serde(default)]
    pub avg_logprob: Option<f32>,
    #[serde(default)]
    pub source_avg_logprob: Option<f32>,
    #[serde(default)]
    pub no_speech_probability: Option<f32>,
    #[serde(default)]
    pub source_no_speech_probability: Option<f32>,
    #[serde(default)]
    pub compression_ratio: Option<f32>,
    #[serde(default)]
    pub probability: Option<f32>,
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub value: Option<u64>,
    #[serde(default)]
    pub delta: Option<u64>,
    #[serde(default)]
    pub quality_passed: Option<bool>,
    #[serde(default)]
    pub quality_issues: Vec<serde_json::Value>,
    #[serde(default)]
    pub glossary_terms: Vec<String>,
    #[serde(default)]
    pub translation_memory_hit: Option<bool>,
    #[serde(default)]
    pub verification_inference_duration_ms: Option<u64>,
    #[serde(default)]
    pub verification_attempted: Option<bool>,
    #[serde(default)]
    pub verification_selected: Option<bool>,
}

#[derive(Clone, Debug)]
pub struct AiWorkerConfig {
    pub python: PathBuf,
    pub script: PathBuf,
    pub model_dir: PathBuf,
    pub preset: String,
    pub model: Option<String>,
    pub device: String,
    pub compute_type: String,
    pub source_language: Option<String>,
    pub allow_model_download: bool,
}

impl AiWorkerConfig {
    pub fn development(python: impl Into<PathBuf>) -> Self {
        Self {
            python: python.into(),
            script: PathBuf::from("ai_worker/worker.py"),
            model_dir: PathBuf::from("models"),
            preset: "balanced".to_owned(),
            model: None,
            device: "auto".to_owned(),
            compute_type: "auto".to_owned(),
            source_language: None,
            allow_model_download: false,
        }
    }
}

#[derive(Default)]
pub struct AiTransportMetrics {
    pub audio_chunks_sent: AtomicU64,
    pub audio_chunks_dropped: AtomicU64,
    pub protocol_errors: AtomicU64,
    pub event_drops: AtomicU64,
}

fn is_priority_event(event: &AiEvent) -> bool {
    event.kind == "error"
        || (event.kind == "transcript" && event.is_final.unwrap_or(false))
        || (event.kind == "status" && event.state.as_deref() == Some("listening"))
}

pub struct AiWorker {
    commands: Sender<AiCommand>,
    events: Receiver<AiEvent>,
    child: Child,
    threads: Vec<JoinHandle<()>>,
    pub metrics: Arc<AiTransportMetrics>,
}

impl Drop for AiWorker {
    fn drop(&mut self) {
        let _ = self.commands.try_send(AiCommand::Shutdown {
            protocol: AI_PROTOCOL_VERSION,
        });
        if self.child.try_wait().ok().flatten().is_none() {
            for _ in 0..50 {
                std::thread::sleep(std::time::Duration::from_millis(20));
                if self.child.try_wait().ok().flatten().is_some() {
                    break;
                }
            }
        }
        if self.child.try_wait().ok().flatten().is_none() {
            tracing::warn!(
                pid = self.child.id(),
                "forcing unresponsive AI worker to stop"
            );
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
        for thread in self.threads.drain(..) {
            let _ = thread.join();
        }
    }
}

fn log_stderr(stderr: ChildStderr) {
    for line in BufReader::new(stderr).lines().map_while(Result::ok) {
        tracing::warn!(worker = %line, "AI worker diagnostic");
    }
}

impl AiWorker {
    pub fn start(config: AiWorkerConfig) -> anyhow::Result<Self> {
        if config.python.is_absolute() || config.python.components().count() > 1 {
            anyhow::ensure!(
                config.python.is_file(),
                "Python executable not found: {}",
                config.python.display()
            );
        }
        anyhow::ensure!(
            config.script.is_file(),
            "AI worker script not found: {}",
            config.script.display()
        );
        let mut child = Command::new(&config.python)
            .arg("-u")
            .arg(&config.script)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .with_context(|| format!("start AI worker with {}", config.python.display()))?;
        let mut stdin = child
            .stdin
            .take()
            .context("AI worker stdin was not piped")?;
        let stdout = child
            .stdout
            .take()
            .context("AI worker stdout was not piped")?;
        let stderr = child
            .stderr
            .take()
            .context("AI worker stderr was not piped")?;

        let (command_sender, command_receiver) = bounded::<AiCommand>(24);
        let (event_sender, event_receiver) = bounded::<AiEvent>(128);
        let metrics = Arc::new(AiTransportMetrics::default());
        let reader_metrics = Arc::clone(&metrics);
        let writer = thread::Builder::new()
            .name("livesub-ai-writer".into())
            .spawn(move || {
                while let Ok(command) = command_receiver.recv() {
                    match serde_json::to_writer(&mut stdin, &command)
                        .and_then(|_| stdin.write_all(b"\n").map_err(serde_json::Error::io))
                        .and_then(|_| stdin.flush().map_err(serde_json::Error::io))
                    {
                        Ok(()) => {}
                        Err(error) => {
                            tracing::error!(%error, "AI worker command pipe failed");
                            break;
                        }
                    }
                    if matches!(command, AiCommand::Shutdown { .. }) {
                        break;
                    }
                }
            })?;
        let reader = thread::Builder::new()
            .name("livesub-ai-reader".into())
            .spawn(move || {
                for line in BufReader::new(stdout).lines() {
                    let Ok(line) = line else { break };
                    match serde_json::from_str::<AiEvent>(&line) {
                        Ok(event) => {
                            let priority = is_priority_event(&event);
                            let sent = match event_sender.try_send(event) {
                                Ok(()) => true,
                                Err(crossbeam_channel::TrySendError::Full(event)) if priority => {
                                    event_sender
                                        .send_timeout(event, Duration::from_millis(250))
                                        .is_ok()
                                }
                                Err(_) => false,
                            };
                            if !sent {
                                reader_metrics.event_drops.fetch_add(1, Ordering::Relaxed);
                            }
                        }
                        Err(error) => {
                            reader_metrics
                                .protocol_errors
                                .fetch_add(1, Ordering::Relaxed);
                            tracing::error!(%error, line = %line, "invalid AI worker event");
                        }
                    }
                }
            })?;
        let stderr_thread = thread::Builder::new()
            .name("livesub-ai-stderr".into())
            .spawn(move || log_stderr(stderr))?;

        let configure = AiCommand::Configure {
            protocol: AI_PROTOCOL_VERSION,
            preset: config.preset,
            model: config.model,
            device: config.device,
            compute_type: config.compute_type,
            model_dir: config.model_dir.to_string_lossy().into_owned(),
            source_language: config.source_language,
            allow_model_download: config.allow_model_download,
        };
        command_sender
            .send(configure)
            .context("queue AI worker configuration")?;

        Ok(Self {
            commands: command_sender,
            events: event_receiver,
            child,
            threads: vec![writer, reader, stderr_thread],
            metrics,
        })
    }

    pub fn try_send_audio(&self, sequence: u64, samples: &[f32]) -> bool {
        let mut pcm = Vec::with_capacity(samples.len() * 2);
        for sample in samples {
            let quantized = (sample.clamp(-1.0, 1.0) * i16::MAX as f32).round() as i16;
            pcm.extend_from_slice(&quantized.to_le_bytes());
        }
        let command = AiCommand::Audio {
            protocol: AI_PROTOCOL_VERSION,
            sequence,
            sample_rate: INTERNAL_SAMPLE_RATE,
            capture_end_unix_ms: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as u64,
            pcm_s16le: base64::engine::general_purpose::STANDARD.encode(pcm),
        };
        match self.commands.try_send(command) {
            Ok(()) => {
                self.metrics
                    .audio_chunks_sent
                    .fetch_add(1, Ordering::Relaxed);
                true
            }
            Err(_) => {
                self.metrics
                    .audio_chunks_dropped
                    .fetch_add(1, Ordering::Relaxed);
                false
            }
        }
    }

    pub fn events(&self) -> &Receiver<AiEvent> {
        &self.events
    }

    pub fn stop(mut self) -> anyhow::Result<()> {
        let _ = self.commands.send(AiCommand::Shutdown {
            protocol: AI_PROTOCOL_VERSION,
        });
        let status = self.child.wait().context("wait for AI worker shutdown")?;
        for thread in self.threads.drain(..) {
            let _ = thread.join();
        }
        anyhow::ensure!(status.success(), "AI worker exited with {status}");
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::{AiEvent, is_priority_event};

    #[test]
    fn minimal_worker_events_do_not_require_transcript_fields() {
        let event: AiEvent = serde_json::from_str(r#"{"type":"hello"}"#)
            .expect("minimal worker control events must remain protocol-compatible");

        assert_eq!(event.kind, "hello");
        assert!(event.text.is_none());
        assert!(event.quality_issues.is_empty());
        assert!(event.glossary_terms.is_empty());
    }

    #[test]
    fn final_transcripts_are_priority_transport_events() {
        let final_event: AiEvent =
            serde_json::from_str(r#"{"type":"transcript","is_final":true,"text":"confirmed"}"#)
                .unwrap();
        let partial_event: AiEvent =
            serde_json::from_str(r#"{"type":"transcript","is_final":false,"text":"tentative"}"#)
                .unwrap();

        assert!(is_priority_event(&final_event));
        assert!(!is_priority_event(&partial_event));
    }

    #[test]
    fn pcm_quantization_is_bounded() {
        let samples = [-2.0_f32, -1.0, 0.0, 1.0, 2.0];
        let mut pcm = Vec::new();
        for sample in samples {
            let quantized = (sample.clamp(-1.0, 1.0) * i16::MAX as f32).round() as i16;
            pcm.push(quantized);
        }
        assert_eq!(pcm, [-32767, -32767, 0, 32767, 32767]);
    }
}
