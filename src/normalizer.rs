use crate::{INTERNAL_SAMPLE_RATE, audio::NativeAudioFrame};

/// Stateful linear resampler used at the realtime capture boundary.
///
/// WASAPI shared-mode mix formats are typically 44.1/48 kHz float stereo. This
/// stage downmixes first, preserves fractional phase across packets, and emits
/// the 16 kHz mono float PCM expected by Whisper/VAD. A higher-order resampler
/// can replace it behind this API without changing capture or inference.
#[derive(Debug)]
pub struct AudioNormalizer {
    input_rate: u32,
    channels: u16,
    phase: f64,
    previous: Option<f32>,
}

impl AudioNormalizer {
    pub fn new(input_rate: u32, channels: u16) -> anyhow::Result<Self> {
        anyhow::ensure!(input_rate > 0, "input sample rate must be nonzero");
        anyhow::ensure!(channels > 0, "input channels must be nonzero");
        Ok(Self {
            input_rate,
            channels,
            phase: 0.0,
            previous: None,
        })
    }

    pub fn normalize(&mut self, frame: &NativeAudioFrame) -> anyhow::Result<Vec<f32>> {
        anyhow::ensure!(
            frame.sample_rate == self.input_rate && frame.channels == self.channels,
            "audio format changed from {} Hz/{} ch to {} Hz/{} ch",
            self.input_rate,
            self.channels,
            frame.sample_rate,
            frame.channels
        );

        let channels = usize::from(self.channels);
        anyhow::ensure!(
            frame.samples.len().is_multiple_of(channels),
            "interleaved sample count is not divisible by channel count"
        );

        let mut mono = Vec::with_capacity(frame.samples.len() / channels + 1);
        if let Some(previous) = self.previous {
            mono.push(previous);
        }
        for interleaved in frame.samples.chunks_exact(channels) {
            let sum: f32 = interleaved.iter().copied().sum();
            mono.push((sum / channels as f32).clamp(-1.0, 1.0));
        }
        self.previous = mono.last().copied();

        if self.input_rate == INTERNAL_SAMPLE_RATE {
            if self.previous.is_some() && !mono.is_empty() {
                mono.remove(0);
            }
            return Ok(mono);
        }

        if mono.len() < 2 {
            return Ok(Vec::new());
        }

        let step = self.input_rate as f64 / INTERNAL_SAMPLE_RATE as f64;
        let mut output = Vec::with_capacity(((mono.len() - 1) as f64 / step).ceil() as usize);
        while self.phase + 1.0 < mono.len() as f64 {
            let left = self.phase.floor() as usize;
            let fraction = (self.phase - left as f64) as f32;
            output.push(mono[left] + (mono[left + 1] - mono[left]) * fraction);
            self.phase += step;
        }
        self.phase -= (mono.len() - 1) as f64;
        Ok(output)
    }
}

#[cfg(test)]
mod tests {
    use std::time::Instant;

    use super::*;

    #[test]
    fn downmixes_and_resamples_48k_stereo() {
        let samples: Vec<f32> = (0..4_800)
            .flat_map(|i| {
                let value = (i as f32 * std::f32::consts::TAU * 440.0 / 48_000.0).sin();
                [value, value]
            })
            .collect();
        let frame = NativeAudioFrame {
            sequence: 0,
            captured_at: Instant::now(),
            sample_rate: 48_000,
            channels: 2,
            samples,
        };
        let mut normalizer = AudioNormalizer::new(48_000, 2).unwrap();
        let output = normalizer.normalize(&frame).unwrap();
        assert!((1_599..=1_601).contains(&output.len()), "{}", output.len());
        assert!(output.iter().all(|sample| (-1.0..=1.0).contains(sample)));
    }

    #[test]
    fn rejects_midstream_format_change() {
        let frame = NativeAudioFrame {
            sequence: 0,
            captured_at: Instant::now(),
            sample_rate: 44_100,
            channels: 1,
            samples: vec![0.0; 441],
        };
        let mut normalizer = AudioNormalizer::new(48_000, 1).unwrap();
        assert!(normalizer.normalize(&frame).is_err());
    }
}
