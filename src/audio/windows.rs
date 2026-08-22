use std::ffi::c_void;
use std::ptr;
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};
use std::thread;
use std::time::{Duration, Instant};

use super::{
    AudioCaptureBackend, AudioDevice, CaptureMetrics, DeviceSelection, NativeAudioFrame,
    capture_handle,
};
use anyhow::{Context, bail};
use crossbeam_channel::Sender;
use windows::Win32::Devices::FunctionDiscovery::PKEY_Device_FriendlyName;
use windows::Win32::Media::Audio::{
    AUDCLNT_BUFFERFLAGS_SILENT, AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_LOOPBACK,
    DEVICE_STATE_ACTIVE, IAudioCaptureClient, IAudioClient, IMMDevice, IMMDeviceEnumerator,
    MMDeviceEnumerator, WAVEFORMATEX, eConsole, eRender,
};
use windows::Win32::System::Com::StructuredStorage::{PropVariantClear, PropVariantToStringAlloc};
use windows::Win32::System::Com::{
    CLSCTX_ALL, COINIT_MULTITHREADED, CoCreateInstance, CoInitializeEx, CoTaskMemFree,
    CoUninitialize, STGM_READ,
};

const WAVE_FORMAT_PCM: u16 = 0x0001;
const WAVE_FORMAT_IEEE_FLOAT: u16 = 0x0003;
const WAVE_FORMAT_EXTENSIBLE: u16 = 0xfffe;
const REFERENCE_TIME_PER_SECOND: i64 = 10_000_000;

#[derive(Default)]
pub struct WindowsAudioBackend;

struct ComApartment;

impl ComApartment {
    fn multithreaded() -> anyhow::Result<Self> {
        unsafe {
            CoInitializeEx(None, COINIT_MULTITHREADED)
                .ok()
                .context("initialize COM for WASAPI")?;
        }
        Ok(Self)
    }
}

impl Drop for ComApartment {
    fn drop(&mut self) {
        unsafe { CoUninitialize() };
    }
}

#[derive(Clone, Copy, Debug)]
enum SampleEncoding {
    Float32,
    Signed16,
    Signed24,
    Signed32,
}

#[derive(Clone, Copy, Debug)]
struct MixFormat {
    sample_rate: u32,
    channels: u16,
    block_align: u16,
    bits_per_sample: u16,
    encoding: SampleEncoding,
}

impl MixFormat {
    unsafe fn from_wave_format(format: *const WAVEFORMATEX) -> anyhow::Result<Self> {
        anyhow::ensure!(!format.is_null(), "WASAPI returned a null mix format");
        let wave = unsafe { &*format };
        let effective_tag = if wave.wFormatTag == WAVE_FORMAT_EXTENSIBLE {
            anyhow::ensure!(wave.cbSize >= 22, "invalid WAVEFORMATEXTENSIBLE size");
            // WAVEFORMATEXTENSIBLE::SubFormat starts 24 bytes from the struct base.
            unsafe { ptr::read_unaligned(format.cast::<u8>().add(24).cast::<u32>()) as u16 }
        } else {
            wave.wFormatTag
        };
        let encoding = match (effective_tag, wave.wBitsPerSample) {
            (WAVE_FORMAT_IEEE_FLOAT, 32) => SampleEncoding::Float32,
            (WAVE_FORMAT_PCM, 16) => SampleEncoding::Signed16,
            (WAVE_FORMAT_PCM, 24) => SampleEncoding::Signed24,
            (WAVE_FORMAT_PCM, 32) => SampleEncoding::Signed32,
            (tag, bits) => bail!("unsupported WASAPI mix format tag={tag:#06x}, bits={bits}"),
        };
        anyhow::ensure!(wave.nSamplesPerSec > 0, "WASAPI mix sample rate is zero");
        anyhow::ensure!(wave.nChannels > 0, "WASAPI mix channel count is zero");
        anyhow::ensure!(wave.nBlockAlign > 0, "WASAPI block alignment is zero");
        Ok(Self {
            sample_rate: wave.nSamplesPerSec,
            channels: wave.nChannels,
            block_align: wave.nBlockAlign,
            bits_per_sample: wave.wBitsPerSample,
            encoding,
        })
    }

    unsafe fn decode(&self, data: *const u8, frames: u32, silent: bool) -> Vec<f32> {
        let sample_count = frames as usize * usize::from(self.channels);
        if silent || data.is_null() {
            return vec![0.0; sample_count];
        }
        let bytes_per_sample = usize::from(self.bits_per_sample / 8);
        let mut output = Vec::with_capacity(sample_count);
        for frame_index in 0..frames as usize {
            let frame = unsafe { data.add(frame_index * usize::from(self.block_align)) };
            for channel in 0..usize::from(self.channels) {
                let sample = unsafe { frame.add(channel * bytes_per_sample) };
                let value = match self.encoding {
                    SampleEncoding::Float32 => unsafe { ptr::read_unaligned(sample.cast::<f32>()) },
                    SampleEncoding::Signed16 => unsafe {
                        ptr::read_unaligned(sample.cast::<i16>()) as f32 / i16::MAX as f32
                    },
                    SampleEncoding::Signed24 => unsafe {
                        let raw = i32::from(*sample)
                            | (i32::from(*sample.add(1)) << 8)
                            | (i32::from(*sample.add(2)) << 16);
                        let signed = (raw << 8) >> 8;
                        signed as f32 / 8_388_607.0
                    },
                    SampleEncoding::Signed32 => unsafe {
                        ptr::read_unaligned(sample.cast::<i32>()) as f32 / i32::MAX as f32
                    },
                };
                output.push(if value.is_finite() {
                    value.clamp(-1.0, 1.0)
                } else {
                    0.0
                });
            }
        }
        output
    }
}

impl WindowsAudioBackend {
    fn enumerator() -> anyhow::Result<IMMDeviceEnumerator> {
        unsafe {
            CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)
                .context("create Windows multimedia device enumerator")
        }
    }

    fn endpoint_id(device: &IMMDevice) -> anyhow::Result<String> {
        unsafe {
            let id = device.GetId().context("read audio endpoint id")?;
            let value = id.to_string().context("decode audio endpoint id")?;
            CoTaskMemFree(Some(id.0.cast::<c_void>()));
            Ok(value)
        }
    }

    fn endpoint_name(device: &IMMDevice) -> anyhow::Result<String> {
        unsafe {
            let store = device
                .OpenPropertyStore(STGM_READ)
                .context("open audio endpoint properties")?;
            let mut value = store
                .GetValue(&PKEY_Device_FriendlyName)
                .context("read audio endpoint friendly name")?;
            let text =
                PropVariantToStringAlloc(&value).context("convert audio endpoint friendly name")?;
            let name = text
                .to_string()
                .context("decode audio endpoint friendly name")?;
            CoTaskMemFree(Some(text.0.cast::<c_void>()));
            PropVariantClear(&mut value).context("release audio endpoint friendly name")?;
            Ok(name)
        }
    }

    fn resolve_device(
        enumerator: &IMMDeviceEnumerator,
        selection: &DeviceSelection,
    ) -> anyhow::Result<IMMDevice> {
        match selection {
            DeviceSelection::Auto => unsafe {
                enumerator
                    .GetDefaultAudioEndpoint(eRender, eConsole)
                    .context("resolve default Windows output device")
            },
            DeviceSelection::Id(id) => {
                let wide: Vec<u16> = id.encode_utf16().chain(Some(0)).collect();
                unsafe {
                    enumerator
                        .GetDevice(windows::core::PCWSTR(wide.as_ptr()))
                        .with_context(|| format!("resolve Windows output device {id}"))
                }
            }
            DeviceSelection::Microphone(_) => {
                bail!("microphone capture is not enabled in the system-audio milestone")
            }
        }
    }

    fn run_capture_session(
        selection: DeviceSelection,
        frames: Sender<NativeAudioFrame>,
        stop: Arc<AtomicBool>,
        metrics: Arc<CaptureMetrics>,
    ) -> anyhow::Result<()> {
        let _apartment = ComApartment::multithreaded()?;
        let enumerator = Self::enumerator()?;
        let device = Self::resolve_device(&enumerator, &selection)?;
        let endpoint_id = Self::endpoint_id(&device)?;
        tracing::info!(%endpoint_id, "opening WASAPI loopback endpoint");

        let audio_client: IAudioClient = unsafe {
            device
                .Activate(CLSCTX_ALL, None)
                .context("activate WASAPI audio client")?
        };
        let format_ptr = unsafe { audio_client.GetMixFormat() }
            .context("query WASAPI shared-mode mix format")?;
        let mix_format = unsafe { MixFormat::from_wave_format(format_ptr) }?;
        tracing::info!(
            sample_rate = mix_format.sample_rate,
            channels = mix_format.channels,
            bits = mix_format.bits_per_sample,
            encoding = ?mix_format.encoding,
            "WASAPI mix format"
        );

        let initialization = unsafe {
            audio_client.Initialize(
                AUDCLNT_SHAREMODE_SHARED,
                AUDCLNT_STREAMFLAGS_LOOPBACK,
                REFERENCE_TIME_PER_SECOND,
                0,
                format_ptr,
                None,
            )
        };
        unsafe { CoTaskMemFree(Some(format_ptr.cast::<c_void>())) };
        initialization.context("initialize WASAPI loopback stream")?;

        let capture_client: IAudioCaptureClient = unsafe {
            audio_client
                .GetService()
                .context("get WASAPI capture service")?
        };
        unsafe { audio_client.Start() }.context("start WASAPI loopback stream")?;

        let result = (|| -> anyhow::Result<()> {
            let mut sequence = 0_u64;
            let mut next_default_check = Instant::now() + Duration::from_secs(1);
            while !stop.load(Ordering::Acquire) {
                if matches!(selection, DeviceSelection::Auto)
                    && Instant::now() >= next_default_check
                {
                    let current_default =
                        unsafe { enumerator.GetDefaultAudioEndpoint(eRender, eConsole) }
                            .context("recheck default Windows output device")?;
                    let current_id = Self::endpoint_id(&current_default)?;
                    if current_id != endpoint_id {
                        bail!("default Windows output device changed to {current_id}");
                    }
                    next_default_check = Instant::now() + Duration::from_secs(1);
                }
                let mut available = unsafe { capture_client.GetNextPacketSize() }
                    .context("query WASAPI packet size")?;
                if available == 0 {
                    thread::sleep(Duration::from_millis(3));
                    continue;
                }
                while available > 0 {
                    let mut data = ptr::null_mut();
                    let mut frame_count = 0_u32;
                    let mut flags = 0_u32;
                    unsafe {
                        capture_client.GetBuffer(
                            &mut data,
                            &mut frame_count,
                            &mut flags,
                            None,
                            None,
                        )
                    }
                    .context("read WASAPI loopback packet")?;

                    let silent = flags & AUDCLNT_BUFFERFLAGS_SILENT.0 as u32 != 0;
                    let samples = unsafe { mix_format.decode(data, frame_count, silent) };
                    unsafe { capture_client.ReleaseBuffer(frame_count) }
                        .context("release WASAPI loopback packet")?;

                    metrics.frames.fetch_add(1, Ordering::Relaxed);
                    metrics
                        .samples
                        .fetch_add(samples.len() as u64, Ordering::Relaxed);
                    if silent {
                        metrics.silent_frames.fetch_add(1, Ordering::Relaxed);
                    }
                    let frame = NativeAudioFrame {
                        sequence,
                        captured_at: Instant::now(),
                        sample_rate: mix_format.sample_rate,
                        channels: mix_format.channels,
                        samples,
                    };
                    sequence = sequence.wrapping_add(1);
                    if frames.try_send(frame).is_err() {
                        metrics.dropped_frames.fetch_add(1, Ordering::Relaxed);
                    }
                    available = unsafe { capture_client.GetNextPacketSize() }
                        .context("query next WASAPI packet size")?;
                }
            }
            Ok(())
        })();

        if let Err(error) = unsafe { audio_client.Stop() } {
            tracing::warn!(%error, "failed to stop WASAPI stream cleanly");
        }
        result
    }

    fn run_capture_supervised(
        selection: DeviceSelection,
        frames: Sender<NativeAudioFrame>,
        stop: Arc<AtomicBool>,
        metrics: Arc<CaptureMetrics>,
    ) -> anyhow::Result<()> {
        let mut retry_delay = Duration::from_millis(250);
        loop {
            let result = Self::run_capture_session(
                selection.clone(),
                frames.clone(),
                Arc::clone(&stop),
                Arc::clone(&metrics),
            );
            if stop.load(Ordering::Acquire) {
                return Ok(());
            }
            match result {
                Ok(()) => return Ok(()),
                Err(error) if matches!(selection, DeviceSelection::Auto) => {
                    metrics.recoveries.fetch_add(1, Ordering::Relaxed);
                    tracing::warn!(%error, ?retry_delay, "WASAPI endpoint lost; retrying AUTO");
                    thread::sleep(retry_delay);
                    retry_delay = (retry_delay * 2).min(Duration::from_secs(4));
                }
                Err(error) => return Err(error),
            }
        }
    }
}

impl AudioCaptureBackend for WindowsAudioBackend {
    fn enumerate_devices(&self) -> anyhow::Result<Vec<AudioDevice>> {
        let _apartment = ComApartment::multithreaded()?;
        let enumerator = Self::enumerator()?;
        let default_id = unsafe {
            enumerator
                .GetDefaultAudioEndpoint(eRender, eConsole)
                .ok()
                .and_then(|device| Self::endpoint_id(&device).ok())
        };
        let collection = unsafe {
            enumerator
                .EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE)
                .context("enumerate active Windows output devices")?
        };
        let count = unsafe { collection.GetCount() }.context("count Windows output devices")?;
        let mut devices = Vec::with_capacity(count as usize);
        for index in 0..count {
            let device = unsafe { collection.Item(index) }
                .with_context(|| format!("open Windows output endpoint {index}"))?;
            let id = Self::endpoint_id(&device)?;
            devices.push(AudioDevice {
                name: Self::endpoint_name(&device).unwrap_or_else(|_| id.clone()),
                is_default: default_id.as_deref() == Some(id.as_str()),
                id,
                is_input: false,
            });
        }
        if devices.is_empty() {
            bail!("no active Windows output device");
        }
        Ok(devices)
    }

    fn start(
        &self,
        selection: DeviceSelection,
        frames: Sender<NativeAudioFrame>,
    ) -> anyhow::Result<super::CaptureHandle> {
        let stop = Arc::new(AtomicBool::new(false));
        let metrics = Arc::new(CaptureMetrics::default());
        let thread_stop = Arc::clone(&stop);
        let thread_metrics = Arc::clone(&metrics);
        let thread = thread::Builder::new()
            .name("livesub-wasapi".into())
            .spawn(move || {
                Self::run_capture_supervised(selection, frames, thread_stop, thread_metrics)
            })
            .context("spawn WASAPI capture thread")?;
        Ok(capture_handle(stop, thread, metrics))
    }
}
