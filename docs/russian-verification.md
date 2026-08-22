# Russian live-translation verification

Observed on 2026-08-22 on Windows x64 with an NVIDIA RTX 4060 8 GB. The balanced preset used faster-whisper `small`, CUDA, and float16. No source language was configured or forced.

## Production path result

The clean-installed application completed this path:

```text
Russian YouTube video in Microsoft Edge
  -> Windows default render endpoint
  -> WASAPI loopback (48 kHz stereo float32)
  -> stateful downmix/resample (16 kHz mono float32)
  -> Silero VAD with 400 ms pre-roll
  -> rolling partials every 800 ms plus VAD final
  -> automatic ru detection with hysteresis
  -> faster-whisper task="translate"
  -> English filtering/stabilization/line breaking
  -> topmost transparent Win32 overlay
```

The screenshot shows the actual Russian gameplay, LiveSub status `Translating`, language `Russian — 100%`, and the independent English overlay: [installed acceptance screenshot](../artifacts/installed-russian-youtube-overlay.png).

## Installed-runtime evidence

The 1.47 GB Inno Setup executable was installed silently to a fresh path. It supplied its own Python 3.12 runtime, exact Python/CUDA dependencies, faster-whisper `small` model, worker, application, Start Menu shortcut, and uninstaller. Installed application and worker SHA-256 values exactly matched the compiled payload. Private imports, CUDA enumeration, the worker protocol test, model transcribe/translate warm-up, desktop launch, normal close, and child cleanup passed.

The installed executable was then started from outside its installation directory with every `LIVESUB_*` override removed. Russian dialogue was rendered to the default Windows output; the app received it only through WASAPI loopback. Results:

| Metric | Observed |
|---|---:|
| Captured WASAPI frames | 3,499 |
| Normalized worker chunks | 350 |
| Capture / AI drops | 0 / 0 |
| Russian inference events | 24 / 24 |
| Stable Russian events | 19 |
| Stable Russian wrong-task events | 0 |
| Mean / maximum inference | 144 / 312 ms |
| Mean / maximum subtitle latency | 153 / 318 ms |
| Backend | CUDA/float16 |

Representative installed English finals included “Hello, I’m glad to see you,” “You are very nice to me, Maria Stepanovna,” and “Thank you, see you, goodbye.”

## Broader Russian coverage

| Source | Result | Evidence |
|---|---|---|
| Clean male narration | PASS | Stable `ru`, English output, zero queue drops. |
| Female narration | PASS | 55 seconds; 58 `ru` events, mean subtitle latency 227 ms. |
| Two-speaker dialogue/names | PASS | Stable `ru`; preserved “Maria Stepanovna.” |
| Extended narration | PASS | 180 seconds; 223/223 `ru` events, zero drops, mean subtitle latency 171 ms. |
| Browser gaming/effects/slang | PASS | Actual Edge/YouTube system audio and overlay; stable `ru`, mean subtitle latency 209 ms. |
| Silence/music-only | PASS | Controlled 10/15 second runs produced zero speech starts and zero finals. |

Across five CUDA Russian runs there were 360 Russian inference events and 181 rendered Russian updates. Stable Russian never used the wrong task. Aggregate inference was mean 166 ms, p95 328 ms; rendered subtitle latency was mean 179 ms, p95 399 ms, max 688 ms; average real-time factor was 0.050.

## Preserved language behavior

One persistent worker processed English, a 13-second silence, Japanese, another 13-second silence, and Hindi. The silence gaps reset the language session. English stabilized with `task="transcribe"`; Japanese and Hindi stabilized with `task="translate"`. The run processed 9,000 capture frames and 900 AI chunks with zero drops. Translation quality on the short Japanese pronunciation drill and parts of the Hindi sample remained mixed, but routing and automatic detection were preserved.

## Known limits

- The installer is not digitally signed; Windows SmartScreen may warn.
- The public gaming run covers fast/excited speech, slang, effects, and multiple voices, but not ten independent streams. A deliberately attenuated quiet-speaker fixture was not run.
- The longest new Russian soak was three minutes, not one hour.
- Default-device recovery is implemented but no controlled Bluetooth/HDMI switch was performed.
- The overlay was verified over normal/maximized Edge; exclusive fullscreen, secure desktops, protected surfaces, and anti-cheat windows remain application/OS dependent.
- The `small` model is fast but can mistranslate names, numerals, short fragments, and overlapping/noisy speech. `medium` and `large-v3` were not acceptance-benchmarked.
