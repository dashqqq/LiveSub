use std::sync::{
    Arc,
    atomic::{AtomicBool, AtomicU64, Ordering},
};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use crossbeam_channel::Sender;
use serde::{Deserialize, Serialize};

#[cfg(windows)]
pub mod windows;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub enum DeviceSelection {
    Auto,
    Id(String),
    Microphone(String),
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AudioDevice {
    pub id: String,
    pub name: String,
    pub is_default: bool,
    pub is_input: bool,
}

#[derive(Clone, Debug)]
pub struct NativeAudioFrame {
    pub sequence: u64,
    pub captured_at: Instant,
    pub sample_rate: u32,
    pub channels: u16,
    pub samples: Vec<f32>,
}

impl NativeAudioFrame {
    pub fn duration(&self) -> Duration {
        if self.sample_rate == 0 || self.channels == 0 {
            return Duration::ZERO;
        }
        Duration::from_secs_f64(
            self.samples.len() as f64 / self.channels as f64 / self.sample_rate as f64,
        )
    }

    pub fn peak(&self) -> f32 {
        self.samples
            .iter()
            .copied()
            .map(f32::abs)
            .fold(0.0, f32::max)
    }

    pub fn rms(&self) -> f32 {
        if self.samples.is_empty() {
            return 0.0;
        }
        let energy: f64 = self
            .samples
            .iter()
            .map(|sample| f64::from(*sample) * f64::from(*sample))
            .sum();
        (energy / self.samples.len() as f64).sqrt() as f32
    }
}

#[derive(Default)]
pub struct CaptureMetrics {
    pub frames: AtomicU64,
    pub samples: AtomicU64,
    pub silent_frames: AtomicU64,
    pub dropped_frames: AtomicU64,
    pub recoveries: AtomicU64,
}

#[derive(Clone, Debug, Serialize)]
pub struct CaptureMetricsSnapshot {
    pub frames: u64,
    pub samples: u64,
    pub silent_frames: u64,
    pub dropped_frames: u64,
    pub recoveries: u64,
}

impl CaptureMetrics {
    pub fn snapshot(&self) -> CaptureMetricsSnapshot {
        CaptureMetricsSnapshot {
            frames: self.frames.load(Ordering::Relaxed),
            samples: self.samples.load(Ordering::Relaxed),
            silent_frames: self.silent_frames.load(Ordering::Relaxed),
            dropped_frames: self.dropped_frames.load(Ordering::Relaxed),
            recoveries: self.recoveries.load(Ordering::Relaxed),
        }
    }
}

pub struct CaptureHandle {
    stop: Arc<AtomicBool>,
    thread: Option<JoinHandle<anyhow::Result<()>>>,
    pub metrics: Arc<CaptureMetrics>,
}

impl CaptureHandle {
    pub fn stop(mut self) -> anyhow::Result<()> {
        self.stop.store(true, Ordering::Release);
        if let Some(thread) = self.thread.take() {
            thread
                .join()
                .map_err(|_| anyhow::anyhow!("audio capture thread panicked"))??;
        }
        Ok(())
    }
}

impl Drop for CaptureHandle {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
    }
}

pub trait AudioCaptureBackend: Send + Sync {
    fn enumerate_devices(&self) -> anyhow::Result<Vec<AudioDevice>>;

    fn start(
        &self,
        selection: DeviceSelection,
        frames: Sender<NativeAudioFrame>,
    ) -> anyhow::Result<CaptureHandle>;
}

pub(crate) fn capture_handle(
    stop: Arc<AtomicBool>,
    thread: JoinHandle<anyhow::Result<()>>,
    metrics: Arc<CaptureMetrics>,
) -> CaptureHandle {
    CaptureHandle {
        stop,
        thread: Some(thread),
        metrics,
    }
}
