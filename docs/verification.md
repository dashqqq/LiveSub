# Verification record

Observed on 2026-08-22, Windows x64, Rust 1.97.1 MSVC, NVIDIA RTX 4060 8 GB. A compile is not treated as proof of realtime behavior.

| Test | Result | Observed evidence |
|---|---|---|
| Rust unit suite | PASS | 9/9: normalization, format mutation rejection, PCM transport, partial stabilization, overlap removal, semantic lines, language adaptation, and overlay alpha conversion. |
| Python protocol self-test/compile | PASS | PCM decode, latest-job replacement, loop collapse, repetition detection, punctuation guard, and module compilation. |
| Endpoint enumeration | PASS | Five active Windows render endpoints; default speakers identified. |
| Real loopback probe | PASS | 5.005 s, 48 kHz stereo float32; 495 packets, 79,200 normalized samples (4.95 s), peak 0.201371, RMS 0.061622, zero drops. |
| English real source | PASS | 2,899 packets / 290 AI chunks / zero drops / four finals. English confidence reached 100%. Most partials were 0.64–1.63 s; finals 1.69–3.00 s. |
| Hindi real source | MIXED | Hindi stabilized at 96.8% with useful partial translations such as “Today I am Kavya Anjali Shukla.” Proper names and one long final were poor; that run exposed and led to the 8 s cap and sentence-loop guard. |
| Japanese real source | MIXED | Japanese stabilized and confidence rose to 97%; CPU partial/final ASR was roughly 0.53–1.22 s and end-to-end 0.54–2.84 s. Short pronunciation-drill translation quality was inconsistent. |
| Japanese→English switch | PASS WITH LAG | One persistent model continued through the switch and relabeled the source English at the reliable final. Stable-language display lagged by one long utterance. |
| Silence, 10 s | PASS | 1,000 capture packets / 100 AI chunks / zero VAD speech starts / zero finals / zero drops. |
| Non-speech Windows music/ringtones, 15 s | PASS | 1,499 packets / 150 chunks / zero speech starts / zero finals / zero drops. |
| CUDA acceleration/fallback | PASS | The installed private runtime passed English transcribe and Russian translate smoke decodes on CUDA/float16. CPU/int8 fallback after a failed CUDA candidate was also verified. |
| Transparent overlay | PASS | Real English system audio rendered on the owned blue surface with no surrounding window rectangle: [acceptance screenshot](../artifacts/overlay-native-monitor1-live.png). |
| Overlay window flags | PASS | Live inspection: layered, tool-window, topmost, no-activate, and click-through all true (`0x080800A8`). |
| Multi-monitor manual placement | PASS | Two displays enumerated; one-based Monitor 1 pin rendered on the selected 1920×1080 display. AUTO also followed the foreground display. |
| Global hotkey and cleanup | PASS | `Ctrl+Shift+S` stopped the AI child while the UI remained responsive. Normal control-window close then exited the desktop process; no LiveSub Python child remained. |
| Sustained real playback, 66 s | PASS | Model remained loaded; 6,599 capture packets / 660 AI chunks / zero capture or AI-audio drops / ten finals. 67 subtitle updates: min 588 ms, mean 1,035 ms, p95 2,012 ms, max 3,111 ms. |
| Russian Edge/YouTube installed overlay | PASS | The clean-installed build captured the Russian gaming video, showed Russian at 100%, and rendered English in the transparent overlay: [screenshot](../artifacts/installed-russian-youtube-overlay.png). |
| Installed Russian CLI evidence | PASS | Started outside the install directory with no `LIVESUB_*` variables: 3,499 WASAPI frames / 350 AI chunks / zero drops; 24/24 events `ru`, 19 stable, zero wrong-task events; mean inference 144 ms and mean subtitle latency 153 ms. |
| Windows installer/clean path | PASS | Self-contained Inno Setup EXE installed private Python, pinned dependencies, model, worker, app, shortcut, and uninstaller. Installed app/worker hashes matched the release payload; private imports/CUDA/self-test and launch passed. |
| Sustained Russian playback, 3 min | PASS | 19,500 capture frames / 1,950 AI chunks / zero drops / 23 finals. Mean inference 148 ms, p95 328 ms, max 422 ms; subtitle latency mean 171 ms, p95 372 ms, max 420 ms. |
| Controlled output-device switch | NOT RUN | Recovery code is implemented, and an incidental endpoint disturbance caused WASAPI to reopen, but there was no safe installed default-device controller for a reproducible switch-and-restore test. |
| Exclusive fullscreen | NOT RUN | Verified over a maximized owned surface and normal desktop apps only. Exclusive fullscreen/secure/protected surfaces remain OS-dependent. |
| One-hour soak | NOT RUN | The bounded 66-second soak passed; a one-hour release soak was not practical in this session. |

## Test media

- English: Wikimedia Commons spoken Wikipedia recording, *The Game* (GFDL): <https://commons.wikimedia.org/wiki/File:The_Game.ogg>
- Hindi: Wikitongues Kavyanjali speaking Hindi (CC BY-SA): <https://commons.wikimedia.org/wiki/File:WIKITONGUES_Kavyanjali_speaking_Hindi.ogg>
- Japanese: native-speaker pronunciation practice, public domain: <https://commons.wikimedia.org/wiki/File:Ja-pronunciation-practice5.ogg>
- Russian narration/dialogue: <https://commons.wikimedia.org/wiki/File:Ru-Russia_part_1_Intro.ogg>, <https://commons.wikimedia.org/wiki/File:Ru-dialog_1.ogg>, <https://commons.wikimedia.org/wiki/File:%D0%9F%D0%BE%D0%B4%D0%BA%D0%B0%D1%81%D1%82%D0%B8%D0%BD%D0%B3.ogg>
- Russian gaming: <https://www.youtube.com/watch?v=JRggeiMYd-c>

The media was decoded only into the Windows default output. LiveSub received it independently through WASAPI loopback; no test samples were injected into the app.

## Current verdict

**RUSSIAN PATH READY; OVERALL PRODUCT PARTIALLY READY.** The clean-installed Russian Edge/YouTube → WASAPI → VAD → auto `ru` → translate → stabilization → overlay path is demonstrated. The overall release still lacks code signing, controlled device-switch and exclusive-fullscreen verification, a one-hour soak, and broader hardware coverage. See [the detailed Russian record](russian-verification.md).
