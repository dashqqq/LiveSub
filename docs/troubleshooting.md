# Troubleshooting LiveSub Preview

## No audio detected

1. Confirm that Windows is playing audible content through the default output device.
2. Start LiveSub after the correct speakers/headphones are selected.
3. Check that the main window shows **Listening** rather than **No system audio**.
4. Stop and restart subtitles after changing an audio endpoint.

LiveSub captures a Windows render endpoint through WASAPI loopback. It does not need the microphone for normal system-audio translation. The automatic default-device recovery path is implemented, but unusual Bluetooth/virtual-device transitions may still require restarting the session.

## Audio is present but no subtitles appear

- Wait for actual speech; music, silence, and low-confidence/no-speech segments are intentionally suppressed.
- Confirm that the overlay is visible with `Ctrl+Shift+H`.
- Unlock it with `Ctrl+Shift+L`, then move it into view.
- Open **Diagnostics** and check VAD state, detected language, model status, queue depth, and dropped audio.
- Very short utterances may not provide enough language evidence.

## The wrong language is detected

Language identification uses accumulated evidence rather than changing on each fragment. Let several seconds of clear speech play. Stop/start subtitles after switching to a different source, or allow sustained silence to clear the language lock. Heavy code switching and closely related languages remain Preview test areas.

## CUDA is unavailable

LiveSub attempts a compatible CUDA/float16 path and performs warm-up smoke decodes. If initialization fails, AUTO mode falls back to CPU/int8. LiveSub does not install or update NVIDIA display drivers.

Update the normal display driver through your hardware vendor if appropriate. Do not install the CUDA Toolkit merely to run the packaged application; its required inference libraries are bundled. CPU mode is slower and may not maintain the target latency on every processor.

## Model initialization fails

The packaged build expects its private runtime and model beside the installed application. Reinstall from the verified release asset if files were quarantined, moved, or only partially installed. Normal execution deliberately refuses to download an unverified missing model.

When reporting this issue, include the application version, the visible error, CPU/GPU model, and whether security software quarantined a file. Do not include transcript text unless it is necessary and safe to share.

## The overlay is not visible

- Press `Ctrl+Shift+H`.
- Unlock with `Ctrl+Shift+L` and check other monitors.
- Select the desired monitor in the LiveSub overlay settings.
- Try borderless windowed mode instead of exclusive fullscreen.

Secure desktops, protected video surfaces, exclusive fullscreen applications, and some anti-cheat systems can prevent normal topmost overlay composition. LiveSub does not attempt to bypass these protections.

## Windows shows “Unknown publisher”

The Preview installer is currently unsigned. This is disclosed on the release and is a stable-release gate. Never disable SmartScreen, Defender, or organizational security controls. If policy blocks unsigned applications, wait for a signed build.

## Subtitles repeat, flash, or lag behind

LiveSub coalesces stale partial jobs, deduplicates overlapping text, and reports queue/drop metrics. Capture cannot wait indefinitely for inference. If problems persist, include the Diagnostics values for total latency, RTF, capture/worker queue depth, dropped audio, and coalesced ASR jobs in a bug report.

## Report a problem

- [Bug report](https://github.com/dashqqq/LiveSub/issues/new?template=bug_report.yml)
- [Translation problem](https://github.com/dashqqq/LiveSub/issues/new?template=translation_accuracy.yml)

Do not upload private or copyrighted audio publicly by default.
