use std::time::Duration;

use eframe::egui::{
    self, Align, Color32, ComboBox, CornerRadius, FontFamily, FontId, Frame, Layout, Margin,
    RichText, Stroke, Vec2, ViewportBuilder,
};

#[cfg(windows)]
use crate::audio::windows::WindowsAudioBackend;
use crate::audio::{AudioCaptureBackend, AudioDevice, DeviceSelection};
#[cfg(windows)]
use crate::overlay::windows::{NativeOverlay, OverlayFrame};
#[cfg(windows)]
use crate::platform::windows::{
    GlobalHotkeys, HotkeyEvent, Monitor, active_monitor, enumerate_monitors,
};
use crate::runtime::{AppStatus, Diagnostics, RuntimeConfig, RuntimeEvent, RuntimeHandle};
use crate::subtitle::{SubtitleSegment, SubtitleUpdate};

const BRAND_ICON_RGBA: &[u8] = include_bytes!("../assets/branding/livesub-icon.rgba");

fn brand_icon_data() -> egui::IconData {
    debug_assert_eq!(BRAND_ICON_RGBA.len(), 256 * 256 * 4);
    egui::IconData {
        rgba: BRAND_ICON_RGBA.to_vec(),
        width: 256,
        height: 256,
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum OverlayPreset {
    Cinema,
    YouTube,
    Minimal,
    Large,
    Accessibility,
}

impl OverlayPreset {
    const ALL: [Self; 5] = [
        Self::Cinema,
        Self::YouTube,
        Self::Minimal,
        Self::Large,
        Self::Accessibility,
    ];

    fn label(self) -> &'static str {
        match self {
            Self::Cinema => "Cinema",
            Self::YouTube => "YouTube",
            Self::Minimal => "Minimal",
            Self::Large => "Large",
            Self::Accessibility => "Accessibility",
        }
    }

    fn style(self) -> OverlayStyle {
        match self {
            Self::Cinema => OverlayStyle::new(34.0, 190, 10, 900.0),
            Self::YouTube => OverlayStyle::new(32.0, 210, 5, 860.0),
            Self::Minimal => OverlayStyle::new(30.0, 100, 4, 820.0),
            Self::Large => OverlayStyle::new(42.0, 210, 12, 1_050.0),
            Self::Accessibility => OverlayStyle::new(46.0, 235, 12, 1_100.0),
        }
    }
}

#[derive(Clone, Copy, Debug)]
struct OverlayStyle {
    font_size: f32,
    background_alpha: u8,
    corner_radius: u8,
    maximum_width: f32,
}

impl OverlayStyle {
    const fn new(
        font_size: f32,
        background_alpha: u8,
        corner_radius: u8,
        maximum_width: f32,
    ) -> Self {
        Self {
            font_size,
            background_alpha,
            corner_radius,
            maximum_width,
        }
    }
}

pub struct LiveSubApp {
    brand_icon: egui::TextureHandle,
    runtime: Option<RuntimeHandle>,
    stop_requested: bool,
    runtime_config: RuntimeConfig,
    status: AppStatus,
    diagnostics: Diagnostics,
    subtitle: Option<SubtitleSegment>,
    devices: Vec<AudioDevice>,
    selected_device: usize,
    overlay_visible: bool,
    overlay_locked: bool,
    show_source_language: bool,
    overlay_preset: OverlayPreset,
    overlay_style: OverlayStyle,
    debug_visible: bool,
    notice: Option<String>,
    #[cfg(windows)]
    monitors: Vec<Monitor>,
    monitor_selection: usize,
    #[cfg(windows)]
    native_overlay: Option<NativeOverlay>,
    #[cfg(windows)]
    hotkeys: GlobalHotkeys,
}

impl LiveSubApp {
    pub fn new(context: &eframe::CreationContext<'_>, start_immediately: bool) -> Self {
        configure_visuals(&context.egui_ctx);
        let brand_icon = context.egui_ctx.load_texture(
            "livesub-brand-icon",
            egui::ColorImage::from_rgba_unmultiplied([256, 256], BRAND_ICON_RGBA),
            egui::TextureOptions::LINEAR,
        );
        #[cfg(windows)]
        let devices = WindowsAudioBackend.enumerate_devices().unwrap_or_default();
        #[cfg(not(windows))]
        let devices = Vec::new();
        #[cfg(windows)]
        let (native_overlay, overlay_notice) = match NativeOverlay::start() {
            Ok(overlay) => (Some(overlay), None),
            Err(error) => (
                None,
                Some(format!("Could not create the subtitle overlay: {error:#}")),
            ),
        };
        #[cfg(not(windows))]
        let overlay_notice = None;
        #[cfg(windows)]
        let monitors = enumerate_monitors();
        #[cfg(windows)]
        let monitor_selection = std::env::var("LIVESUB_MONITOR")
            .ok()
            .and_then(|value| value.parse::<usize>().ok())
            .filter(|index| *index <= monitors.len())
            .unwrap_or(0);
        #[cfg(not(windows))]
        let monitor_selection = 0;

        let mut app = Self {
            brand_icon,
            runtime: None,
            stop_requested: false,
            runtime_config: RuntimeConfig::from_environment(),
            status: AppStatus::Stopped,
            diagnostics: Diagnostics::default(),
            subtitle: None,
            devices,
            selected_device: 0,
            overlay_visible: true,
            overlay_locked: true,
            show_source_language: false,
            overlay_preset: OverlayPreset::Cinema,
            overlay_style: OverlayPreset::Cinema.style(),
            debug_visible: false,
            notice: overlay_notice,
            #[cfg(windows)]
            monitors,
            monitor_selection,
            #[cfg(windows)]
            native_overlay,
            #[cfg(windows)]
            hotkeys: GlobalHotkeys::register(),
        };
        if start_immediately {
            app.start();
        }
        app
    }

    fn is_running(&self) -> bool {
        self.runtime.is_some()
    }

    fn start(&mut self) {
        if self.runtime.is_some() {
            return;
        }
        self.runtime_config.audio_device = if self.selected_device == 0 {
            DeviceSelection::Auto
        } else {
            self.devices
                .get(self.selected_device - 1)
                .map(|device| DeviceSelection::Id(device.id.clone()))
                .unwrap_or(DeviceSelection::Auto)
        };
        match RuntimeHandle::start(self.runtime_config.clone()) {
            Ok(runtime) => {
                self.runtime = Some(runtime);
                self.stop_requested = false;
                self.status = AppStatus::Starting;
                self.subtitle = None;
                self.notice = None;
            }
            Err(error) => {
                self.status = AppStatus::Error;
                self.notice = Some(format!("{error:#}"));
            }
        }
    }

    fn stop(&mut self) {
        if let Some(runtime) = &self.runtime {
            runtime.request_stop();
            self.stop_requested = true;
            self.status = AppStatus::Paused;
        } else {
            self.status = AppStatus::Stopped;
        }
        self.subtitle = None;
    }

    fn poll_runtime(&mut self) {
        let events = self
            .runtime
            .as_ref()
            .map(|runtime| runtime.events().try_iter().collect::<Vec<_>>())
            .unwrap_or_default();
        for event in events {
            match event {
                RuntimeEvent::Status(status) => self.status = status,
                RuntimeEvent::Subtitle(SubtitleUpdate::Upsert { segment }) => {
                    self.subtitle = Some(segment);
                }
                RuntimeEvent::Subtitle(SubtitleUpdate::Clear { segment_id }) => {
                    if self.subtitle.as_ref().map(|segment| segment.id) == Some(segment_id) {
                        self.subtitle = None;
                    }
                }
                RuntimeEvent::Diagnostics(diagnostics) => self.diagnostics = *diagnostics,
                RuntimeEvent::Error(message) => self.notice = Some(message),
            }
        }
        if self
            .runtime
            .as_ref()
            .is_some_and(RuntimeHandle::is_finished)
        {
            // The join is non-blocking now that the worker has exited. Keeping
            // the handle until this point prevents Stop from freezing egui.
            if let Some(mut runtime) = self.runtime.take() {
                runtime.stop();
            }
            self.stop_requested = false;
            if self.status != AppStatus::Error {
                self.status = AppStatus::Stopped;
            }
        }
    }

    #[cfg(windows)]
    fn poll_hotkeys(&mut self) {
        let events = self.hotkeys.events().try_iter().collect::<Vec<_>>();
        for event in events {
            match event {
                HotkeyEvent::ToggleSubtitles => {
                    if self.stop_requested {
                        continue;
                    } else if self.is_running() {
                        self.stop();
                    } else {
                        self.start();
                    }
                }
                HotkeyEvent::ToggleOverlay => self.overlay_visible = !self.overlay_visible,
                HotkeyEvent::IncreaseText => {
                    self.overlay_style.font_size = (self.overlay_style.font_size + 2.0).min(72.0);
                }
                HotkeyEvent::DecreaseText => {
                    self.overlay_style.font_size = (self.overlay_style.font_size - 2.0).max(18.0);
                }
                HotkeyEvent::ToggleLock => self.overlay_locked = !self.overlay_locked,
            }
        }
    }

    #[cfg(not(windows))]
    fn poll_hotkeys(&mut self) {}

    fn status_color(&self) -> Color32 {
        match self.status {
            AppStatus::Listening | AppStatus::SpeechDetected => Color32::from_rgb(62, 215, 150),
            AppStatus::LoadingModel
            | AppStatus::InitializingGpu
            | AppStatus::ConnectingAudio
            | AppStatus::Starting
            | AppStatus::Transcribing
            | AppStatus::Translating => Color32::from_rgb(250, 187, 76),
            AppStatus::Error | AppStatus::NoAudio => Color32::from_rgb(245, 102, 107),
            AppStatus::Paused | AppStatus::Stopped => Color32::from_rgb(132, 143, 165),
        }
    }

    fn control_window(&mut self, ctx: &egui::Context) {
        egui::CentralPanel::default()
            .frame(Frame::new().fill(Color32::from_rgb(16, 19, 27)))
            .show(ctx, |ui| {
                ui.add_space(10.0);
                ui.horizontal(|ui| {
                    ui.image((self.brand_icon.id(), Vec2::splat(36.0)));
                    ui.vertical(|ui| {
                        ui.label(
                            RichText::new("LiveSub")
                                .font(FontId::new(26.0, FontFamily::Proportional))
                                .strong()
                                .color(Color32::WHITE),
                        );
                        ui.label(
                            RichText::new("Accuracy-first English subtitles")
                                .size(12.0)
                                .color(Color32::from_rgb(151, 160, 180)),
                        );
                    });
                    ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                        ui.label(
                            RichText::new("LOCAL PROCESSING")
                                .size(10.0)
                                .color(Color32::from_rgb(100, 220, 174)),
                        );
                    });
                });
                ui.add_space(20.0);

                Frame::new()
                    .fill(Color32::from_rgb(23, 28, 39))
                    .corner_radius(CornerRadius::same(10))
                    .inner_margin(Margin::symmetric(14, 12))
                    .show(ui, |ui| {
                        ui.horizontal(|ui| {
                            let (rect, _) =
                                ui.allocate_exact_size(Vec2::splat(10.0), egui::Sense::hover());
                            ui.painter()
                                .circle_filled(rect.center(), 5.0, self.status_color());
                            ui.label(
                                RichText::new(self.status.label())
                                    .size(16.0)
                                    .strong()
                                    .color(Color32::WHITE),
                            );
                        });
                        ui.add_space(8.0);
                        info_row(ui, "Audio", &self.audio_label());
                        info_row(ui, "Language", &self.language_label());
                        info_row(ui, "Translate", "→ English");
                        info_row(ui, "Model", &self.runtime_config.preset);
                    });

                if let Some(notice) = &self.notice {
                    ui.add_space(10.0);
                    Frame::new()
                        .fill(Color32::from_rgba_unmultiplied(114, 67, 30, 110))
                        .corner_radius(CornerRadius::same(7))
                        .inner_margin(Margin::same(9))
                        .show(ui, |ui| {
                            ui.label(
                                RichText::new(notice)
                                    .size(12.0)
                                    .color(Color32::from_rgb(255, 211, 149)),
                            );
                        });
                }

                ui.add_space(14.0);
                let button_text = if self.stop_requested {
                    "Stopping..."
                } else if self.is_running() {
                    "Stop subtitles"
                } else {
                    "Start live subtitles"
                };
                let button = egui::Button::new(RichText::new(button_text).size(15.0).strong())
                    .fill(if self.is_running() {
                        Color32::from_rgb(69, 76, 92)
                    } else {
                        Color32::from_rgb(100, 92, 246)
                    })
                    .corner_radius(CornerRadius::same(8))
                    .min_size(Vec2::new(ui.available_width(), 42.0));
                if ui.add_enabled(!self.stop_requested, button).clicked() {
                    if self.is_running() {
                        self.stop();
                    } else {
                        self.start();
                    }
                }

                ui.add_space(14.0);
                egui::CollapsingHeader::new(RichText::new("Audio & AI model").strong())
                    .default_open(false)
                    .show(ui, |ui| {
                        ui.horizontal(|ui| {
                            ui.label("Input");
                            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                                ComboBox::from_id_salt("audio-device")
                                    .selected_text(self.audio_label())
                                    .width(260.0)
                                    .show_ui(ui, |ui| {
                                        ui.selectable_value(
                                            &mut self.selected_device,
                                            0,
                                            "AUTO — system default",
                                        );
                                        for (index, device) in self.devices.iter().enumerate() {
                                            ui.selectable_value(
                                                &mut self.selected_device,
                                                index + 1,
                                                &device.name,
                                            );
                                        }
                                    });
                            });
                        });
                        ui.horizontal(|ui| {
                            ui.label("Quality");
                            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                                ComboBox::from_id_salt("quality-preset")
                                    .selected_text(self.runtime_config.preset.to_uppercase())
                                    .show_ui(ui, |ui| {
                                        for preset in ["fast", "balanced", "accurate"] {
                                            ui.selectable_value(
                                                &mut self.runtime_config.preset,
                                                preset.to_owned(),
                                                preset.to_uppercase(),
                                            );
                                        }
                                    });
                            });
                        });
                        ui.horizontal(|ui| {
                            ui.label("Backend");
                            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                                ComboBox::from_id_salt("inference-device")
                                    .selected_text(
                                        self.runtime_config.inference_device.to_uppercase(),
                                    )
                                    .show_ui(ui, |ui| {
                                        for device in ["auto", "cuda", "cpu"] {
                                            ui.selectable_value(
                                                &mut self.runtime_config.inference_device,
                                                device.to_owned(),
                                                device.to_uppercase(),
                                            );
                                        }
                                    });
                            });
                        });
                        ui.label(
                            RichText::new("Changes apply the next time subtitles start.")
                                .size(11.0)
                                .color(Color32::from_rgb(130, 140, 160)),
                        );
                    });

                egui::CollapsingHeader::new(RichText::new("Overlay").strong())
                    .default_open(false)
                    .show(ui, |ui| {
                        ui.horizontal(|ui| {
                            ui.checkbox(&mut self.overlay_visible, "Show overlay");
                            ui.checkbox(&mut self.overlay_locked, "Lock / click-through");
                        });
                        ui.checkbox(
                            &mut self.show_source_language,
                            "Show source language above English",
                        );
                        #[cfg(windows)]
                        ui.horizontal(|ui| {
                            ui.label("Monitor");
                            ComboBox::from_id_salt("overlay-monitor")
                                .selected_text(if self.monitor_selection == 0 {
                                    "AUTO — active window".to_owned()
                                } else {
                                    self.monitors
                                        .get(self.monitor_selection - 1)
                                        .map(|monitor| monitor.name.clone())
                                        .unwrap_or_else(|| "AUTO — active window".into())
                                })
                                .show_ui(ui, |ui| {
                                    ui.selectable_value(
                                        &mut self.monitor_selection,
                                        0,
                                        "AUTO — active window",
                                    );
                                    for (index, monitor) in self.monitors.iter().enumerate() {
                                        let label = format!(
                                            "Monitor {} — {}×{}{}",
                                            index + 1,
                                            monitor.width,
                                            monitor.height,
                                            if monitor.is_primary { " (primary)" } else { "" }
                                        );
                                        ui.selectable_value(
                                            &mut self.monitor_selection,
                                            index + 1,
                                            label,
                                        );
                                    }
                                });
                        });
                        ui.horizontal(|ui| {
                            ui.label("Style");
                            ComboBox::from_id_salt("overlay-preset")
                                .selected_text(self.overlay_preset.label())
                                .show_ui(ui, |ui| {
                                    for preset in OverlayPreset::ALL {
                                        if ui
                                            .selectable_value(
                                                &mut self.overlay_preset,
                                                preset,
                                                preset.label(),
                                            )
                                            .clicked()
                                        {
                                            self.overlay_style = preset.style();
                                        }
                                    }
                                });
                            ui.add(
                                egui::Slider::new(&mut self.overlay_style.font_size, 22.0..=64.0)
                                    .suffix(" px"),
                            );
                        });
                    });

                egui::CollapsingHeader::new(RichText::new("Diagnostics").strong())
                    .default_open(self.debug_visible)
                    .show(ui, |ui| diagnostics_grid(ui, &self.diagnostics));

                ui.with_layout(Layout::bottom_up(Align::Center), |ui| {
                    ui.label(
                        RichText::new("Ctrl+Shift+S  start/stop   •   Ctrl+Shift+L  lock overlay")
                            .size(10.0)
                            .color(Color32::from_rgb(108, 117, 138)),
                    );
                });
            });
    }

    fn audio_label(&self) -> String {
        if self.selected_device == 0 {
            self.devices
                .iter()
                .find(|device| device.is_default)
                .map(|device| format!("AUTO — {}", device.name))
                .unwrap_or_else(|| "AUTO — system default".into())
        } else {
            self.devices
                .get(self.selected_device - 1)
                .map(|device| device.name.clone())
                .unwrap_or_else(|| "AUTO — system default".into())
        }
    }

    fn language_label(&self) -> String {
        if self.diagnostics.detected_language.is_empty() {
            "Auto detect".into()
        } else {
            format!(
                "{} — {:.0}%",
                language_name(&self.diagnostics.detected_language),
                self.diagnostics.language_confidence * 100.0
            )
        }
    }

    #[cfg(windows)]
    fn overlay(&mut self) {
        let Some(overlay) = &self.native_overlay else {
            return;
        };
        let monitor = if self.monitor_selection == 0 {
            active_monitor()
        } else {
            self.monitors.get(self.monitor_selection - 1).cloned()
        };
        let width = self.overlay_style.maximum_width.round() as i32;
        let height = 190;
        let (x, y) = monitor
            .map(|monitor| {
                (
                    monitor.x + (monitor.width - width).max(0) / 2,
                    monitor.y + (monitor.height - height - 40).max(0),
                )
            })
            .unwrap_or((0, 0));
        let text = self
            .subtitle
            .as_ref()
            .map(|segment| {
                let english = segment.display_lines.join("\r\n");
                if self.show_source_language {
                    segment
                        .original_text
                        .as_ref()
                        .filter(|source| !source.trim().is_empty())
                        .map(|source| format!("{source}\r\n{english}"))
                        .unwrap_or(english)
                } else {
                    english
                }
            })
            .or_else(|| {
                matches!(
                    self.status,
                    AppStatus::Starting | AppStatus::LoadingModel | AppStatus::SpeechDetected
                )
                .then(|| self.status.label().to_owned())
            })
            .unwrap_or_default();
        let tentative = self
            .subtitle
            .as_ref()
            .is_some_and(|segment| segment.is_partial);
        let longest_line = text
            .split("\r\n")
            .map(|line| line.chars().count())
            .max()
            .unwrap_or_default();
        let adaptive_font_size = if longest_line > 44 {
            (self.overlay_style.font_size * 44.0 / longest_line as f32).max(18.0)
        } else {
            self.overlay_style.font_size
        };
        overlay.update(OverlayFrame {
            text,
            visible: self.overlay_visible,
            locked: self.overlay_locked,
            x,
            y,
            width,
            height,
            font_size: adaptive_font_size,
            background_alpha: self.overlay_style.background_alpha,
            corner_radius: self.overlay_style.corner_radius,
            tentative,
        });
    }

    #[cfg(not(windows))]
    fn overlay(&mut self) {}
}

impl eframe::App for LiveSubApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.poll_hotkeys();
        self.poll_runtime();
        self.control_window(ctx);
        self.overlay();
        ctx.request_repaint_after(Duration::from_millis(50));
    }

    fn clear_color(&self, _visuals: &egui::Visuals) -> [f32; 4] {
        // Exact black is the Windows chroma key for the secondary overlay.
        // The control window covers its root surface with an opaque panel.
        [0.0, 0.0, 0.0, 1.0]
    }

    fn on_exit(&mut self, _gl: Option<&eframe::glow::Context>) {
        self.stop();
    }
}

fn configure_visuals(ctx: &egui::Context) {
    let mut visuals = egui::Visuals::dark();
    visuals.panel_fill = Color32::from_rgb(16, 19, 27);
    visuals.window_fill = Color32::from_rgb(20, 24, 34);
    visuals.widgets.inactive.bg_fill = Color32::from_rgb(31, 36, 48);
    visuals.widgets.inactive.bg_stroke = Stroke::new(1.0_f32, Color32::from_rgb(49, 56, 72));
    visuals.widgets.hovered.bg_fill = Color32::from_rgb(43, 49, 65);
    visuals.selection.bg_fill = Color32::from_rgb(100, 92, 246);
    ctx.set_visuals(visuals);
    let mut style = (*ctx.style()).clone();
    style.spacing.item_spacing = Vec2::new(8.0, 8.0);
    style.spacing.button_padding = Vec2::new(12.0, 7.0);
    ctx.set_style(style);
}

fn info_row(ui: &mut egui::Ui, label: &str, value: &str) {
    ui.horizontal(|ui| {
        ui.label(
            RichText::new(label)
                .size(12.0)
                .color(Color32::from_rgb(137, 148, 169)),
        );
        ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
            ui.label(
                RichText::new(value)
                    .size(12.0)
                    .color(Color32::from_rgb(226, 230, 238)),
            );
        });
    });
}

fn diagnostics_grid(ui: &mut egui::Ui, diagnostics: &Diagnostics) {
    egui::Grid::new("diagnostics-grid")
        .num_columns(2)
        .spacing([14.0, 5.0])
        .striped(true)
        .show(ui, |ui| {
            diagnostic(
                ui,
                "Format",
                format!(
                    "{} Hz / {} ch",
                    diagnostics.sample_rate, diagnostics.channels
                ),
            );
            diagnostic(
                ui,
                "Audio",
                format!(
                    "peak {:.3}  rms {:.3}",
                    diagnostics.audio_peak, diagnostics.audio_rms
                ),
            );
            diagnostic(ui, "VAD", diagnostics.vad_state.clone());
            diagnostic(
                ui,
                "Language detector",
                if diagnostics.language_candidate.is_empty() {
                    "waiting for speech".into()
                } else {
                    format!(
                        "{} ({}) {:.0}%",
                        diagnostics.language_candidate,
                        if diagnostics.language_stable {
                            "stable"
                        } else {
                            "candidate"
                        },
                        diagnostics.language_confidence * 100.0
                    )
                },
            );
            diagnostic(ui, "Model", diagnostics.model.clone());
            diagnostic(ui, "Backend", diagnostics.inference_backend.clone());
            diagnostic(ui, "GPU", diagnostics.gpu.clone());
            diagnostic(ui, "ASR engine", diagnostics.asr_engine.clone());
            diagnostic(ui, "Translator", diagnostics.translation_engine.clone());
            diagnostic(ui, "Whisper task", diagnostics.inference_task.clone());
            diagnostic(
                ui,
                "Audio window",
                optional_ms(diagnostics.audio_duration_ms),
            );
            diagnostic(
                ui,
                "Inference",
                optional_ms(diagnostics.inference_duration_ms),
            );
            diagnostic(
                ui,
                "Real-time factor",
                diagnostics
                    .real_time_factor
                    .map(|value| format!("{value:.2}x"))
                    .unwrap_or_else(|| "—".into()),
            );
            diagnostic(
                ui,
                "ASR confidence signals",
                format!(
                    "logp {}  no-speech {}  compression {}",
                    optional_float(diagnostics.avg_logprob),
                    optional_float(diagnostics.no_speech_probability),
                    optional_float(diagnostics.compression_ratio)
                ),
            );
            diagnostic(
                ui,
                "Translation memory",
                if diagnostics.translation_memory_hit {
                    "Exact session match".to_owned()
                } else {
                    "No match".to_owned()
                },
            );
            diagnostic(
                ui,
                "Semantic checks",
                match diagnostics.quality_passed {
                    Some(true) if diagnostics.quality_issue_count == 0 => "Passed".to_owned(),
                    Some(_) => format!("{} issue(s)", diagnostics.quality_issue_count),
                    None => "Not available".to_owned(),
                },
            );
            diagnostic(
                ui,
                "Semantic verification",
                if diagnostics.verification_selected {
                    format!(
                        "Stronger correction selected ({})",
                        optional_ms(diagnostics.verification_inference_duration_ms)
                    )
                } else if diagnostics.verification_attempted {
                    format!(
                        "Checked; original retained ({})",
                        optional_ms(diagnostics.verification_inference_duration_ms)
                    )
                } else {
                    "Not needed".to_owned()
                },
            );
            diagnostic(ui, "ASR latency", optional_ms(diagnostics.asr_latency_ms));
            diagnostic(
                ui,
                "Translation latency",
                optional_ms(diagnostics.translation_latency_ms),
            );
            diagnostic(
                ui,
                "Total latency",
                optional_ms(diagnostics.total_latency_ms),
            );
            diagnostic(
                ui,
                "Capture queue",
                format!(
                    "{}/{}",
                    diagnostics.capture_queue_depth, diagnostics.capture_queue_capacity
                ),
            );
            diagnostic(
                ui,
                "Captured / dropped",
                format!(
                    "{} / {}",
                    diagnostics.captured_frames, diagnostics.dropped_frames
                ),
            );
            diagnostic(
                ui,
                "AI transport dropped",
                diagnostics.dropped_ai_chunks.to_string(),
            );
            diagnostic(
                ui,
                "Worker audio dropped",
                diagnostics.dropped_worker_audio_chunks.to_string(),
            );
            diagnostic(
                ui,
                "Worker events dropped",
                diagnostics.dropped_worker_events.to_string(),
            );
            diagnostic(
                ui,
                "ASR jobs coalesced",
                diagnostics.coalesced_asr_jobs.to_string(),
            );
            diagnostic(ui, "Recoveries", diagnostics.recoveries.to_string());
        });
}

fn diagnostic(ui: &mut egui::Ui, label: &str, value: String) {
    ui.label(
        RichText::new(label)
            .size(11.0)
            .color(Color32::from_rgb(130, 140, 160)),
    );
    ui.label(
        RichText::new(value)
            .size(11.0)
            .monospace()
            .color(Color32::from_rgb(218, 222, 231)),
    );
    ui.end_row();
}

fn optional_ms(value: Option<u64>) -> String {
    value.map_or_else(|| "—".into(), |value| format!("{value} ms"))
}

fn optional_float(value: Option<f32>) -> String {
    value.map_or_else(|| "—".into(), |value| format!("{value:.2}"))
}

fn language_name(code: &str) -> &str {
    match code {
        "en" => "English",
        "ja" => "Japanese",
        "ko" => "Korean",
        "hi" => "Hindi",
        "fr" => "French",
        "de" => "German",
        "es" => "Spanish",
        "pt" => "Portuguese",
        "ru" => "Russian",
        "ar" => "Arabic",
        "zh" => "Chinese",
        "it" => "Italian",
        "th" => "Thai",
        "bn" => "Bengali",
        "ta" => "Tamil",
        "te" => "Telugu",
        "mr" => "Marathi",
        "as" => "Assamese",
        other => other,
    }
}

pub fn run(start_immediately: bool) -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: ViewportBuilder::default()
            .with_title("LiveSub")
            .with_icon(brand_icon_data())
            .with_inner_size([430.0, 570.0])
            .with_min_inner_size([390.0, 520.0])
            .with_resizable(true)
            .with_transparent(false),
        renderer: eframe::Renderer::Glow,
        vsync: true,
        ..Default::default()
    };
    eframe::run_native(
        "LiveSub",
        options,
        Box::new(move |context| Ok(Box::new(LiveSubApp::new(context, start_immediately)))),
    )
}
