# Accuracy campaign verification — 2026-08-22

> **Historical record:** this document describes a superseded pre-clearance
> engineering artifact and preserves its original measurements. It is not the
> public v0.1.0 installer. See the
> [v0.1.0 redistribution record](../release/redistribution-clearance-v0.1.0-preview.md)
> and [Preview release](https://github.com/dashqqq/LiveSub/releases/tag/v0.1.0)
> for the published artifact, checksum, and current clearance.

## Final tested setup artifact

- Path: `dist/LiveSub-Setup.exe`
- Size: 1,473,166,025 bytes
- SHA-256: `8C2AA6FC69F13484E0C3F43B202585100FCFE35CD099485FD2985397CFAC35BE`
- Inno Setup: 6.7.3, per-user x64 install
- Fresh validation target:
  `artifacts/installed-accuracy-postreview-20260822` (local verification output; excluded from the public repository)

This setup filename was emitted directly by the final packaging run after the
senior-review source fixes. Both the setup and installed app are currently
unsigned (`Get-AuthenticodeSignature: NotSigned`). The compiler identified its
current activation as `Non-commercial use only`; commercial-use status must be
resolved through license procurement/activation or documented legal approval,
then the setup rebuilt before commercial release.

## Installed-tree gates passed

- Silent install returned exit code 0 into a fresh directory.
- No system Python, Node, Rust, FFmpeg, or CUDA Toolkit was used by the installed
  application.
- Private Python worker protocol self-test passed.
- `language_id`, `language_packs`, and Ed25519 verification imports passed from
  the installed tree.
- The unsigned development registry failed closed under production defaults.
- Bundled faster-whisper-small warmed on CUDA float16.
- Rust accepted worker hello/start/GPU/listening events.
- WASAPI loopback opened the default 48 kHz stereo Float32 endpoint.
- Installed `worker.py` and `livesub.exe` were byte-for-byte equal to the final
  reviewed source worker and release build.
- Installed worker source SHA-256:
  `022E30C10D5D45D1A4AC54900A4E20A138DF9C94C4A41EA39964B7CDAE82D8BC`.
- Installed native executable SHA-256:
  `072424AED372FE8A27D1B1144686C5364FF77434F5FCBEC1A2CC90EFD6CBAD31`.

## Real installed Russian system-audio test

The Russian dialogue fixture was rendered through the Windows output device by
a separate playback process. The freshly installed application captured the
same device through WASAPI loopback; audio was not passed directly to ASR.

- Installed app exit: 0
- Playback exit: 0
- Final transcript events observed: 5
- Finals with preserved Cyrillic source transcript: 5
- `asr_failed` events: 0
- Capture frames reported: 1,326
- AI audio chunks reported: 133
- Capture drops: 0
- AI transport drops: 0

Example installed final:

```text
Source: Здравствуйте! Я рад вас видеть! Добрый день! Я тоже!
English: Hello! I'm glad to see you! Good afternoon! And I too!
```

This run also verified source-final timing, semantic quality fields, and the
translation-memory/verification diagnostics in the installed Rust protocol.

## Final post-review installed Russian smoke

After the translation-memory, event-priority, protocol regression, tentative
styling, and no-truncation fixes, the final setup was rebuilt and installed into
the fresh target above. `russian-dialog.ogg` was rendered by a separate process
through the Windows output device and captured independently through WASAPI.

- Installed app / playback exit: 0 / 0
- CUDA backend: float16, one CUDA device
- Final transcript events: 4
- Finals with preserved Cyrillic source: 4
- Capture frames / AI chunks: 1,019 / 102
- Capture / AI transport drops: 0 / 0
- Final source example: `Меня зовут Джон. А вас?`
- Final English example: `My name is John, and you?`
- Observed final end-to-end latencies in this short smoke: 298–600 ms

The capture-only check separately recorded 332 WASAPI frames, 318,720 native
samples, 53,120 normalized samples, peak 0.416, and zero drops. A screenshot of
the final installed native overlay is stored at
`artifacts/overlay-postreview-installed-20260822.png`; visual inspection confirms
the two-line confirmed subtitle is readable and retains its complete meaning.

## Real installed Japanese and Hindi system-audio tests

The same final installed executable captured separately rendered Japanese and
Hindi fixtures through WASAPI loopback.

| Fixture | Final events | Expected-language finals | Finals with source text | ASR failures | Capture / AI drops |
| --- | ---: | ---: | ---: | ---: | ---: |
| Japanese | 5 | 4 Japanese | 5 | 0 | 0 / 0 |
| Hindi | 3 | 2 Hindi | 3 | 0 | 0 / 0 |

The Japanese fixture begins with the English phrase “Thank you,” which was
detected as English before Japanese speech. The first very short Hindi utterance
was misdetected as low-confidence Russian and suppressed; accumulated evidence
then produced Hindi finals. This is an honest short-utterance LID limitation and
remains part of the golden-corpus gate rather than being labelled a pass.

## Regressions found and fixed by clean-payload testing

1. The packaging manifest omitted `language_id.py` and `language_packs.py`.
2. The embedded Python `_pth` file excluded the application root.
3. The Ed25519 verification runtime was absent.
4. `allow_model_download` was accidentally required on worker output events.
5. Windows legacy stdout encoding rejected final Russian source text while
   ASCII partial translations appeared healthy. Protocol stdout is now UTF-8.
6. Semantically failed translations could enter session translation memory.
7. Long display layout could discard leading words to stay within two lines.
8. Bounded event queues treated final transcripts like disposable partials.

The last three are covered by unit tests or bounded priority logic in the final
post-review build. Current source checks pass 39 Python tests and 12 Rust tests,
plus formatting, `cargo check`, and Clippy with warnings denied.

## Not a clean-machine release certification

The post-review install target was fresh and the installed executable/runtime/model paths
were isolated from source paths, but the test machine still contained the
development repository and toolchains. All three default languages were
replayed through an installed WASAPI path; Russian was repeated through the
final post-review setup. This is still a strong
clean-payload test rather than the mandatory repository-absent clean-machine
certification.

## Accuracy gate status

The release is **not accuracy-selection ready**. Russian, Japanese, and Hindi
have zero human-approved golden cases. WER, CER, chrF++, COMET, corpus-backed
critical errors, hallucination rate, 30-minute per-language soak, fourth-
language installation, signed production registry, and clean-machine testing
remain blocked/pending. See `artifacts/accuracy-scorecard-live-policy-20260822.md`.
