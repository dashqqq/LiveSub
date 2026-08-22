# Accuracy-first repository audit

Audit date: 2026-08-22. This document describes the repository before the
accuracy-first implementation campaign. It separates observed behavior from
claims that still require a corpus and measurement.

## CURRENT ARCHITECTURE

### Product and desktop stack

- The application is a native Rust desktop program, not Tauri. The control
  window uses `eframe`/`egui` 0.32.3 with an OpenGL renderer.
- Windows integration is implemented through the `windows` crate. A dedicated
  Win32 layered window renders the subtitle using a premultiplied BGRA DIB and
  `UpdateLayeredWindow`.
- The overlay is topmost, a tool window, no-activate, and click-through when
  locked. It is manually positionable by monitor and draggable when unlocked.
  Overlay frames use a one-slot bounded channel.
- Global hotkeys are registered on a dedicated Win32 message-loop thread.
- The normal UI has one control page with audio/model controls, overlay controls,
  and a collapsible diagnostics grid. There is no tray, first-run flow, language
  library, persistent settings store, or model download UI.

### Audio capture and conditioning

- `WindowsAudioBackend` enumerates active render endpoints and captures the
  selected endpoint using shared-mode WASAPI loopback. No microphone is needed.
- AUTO follows the `eConsole` default render endpoint. The endpoint ID is checked
  every second; loss or change causes a supervised reopen with 250 ms to 4 s
  exponential backoff.
- Float32, signed 16-bit, signed packed 24-bit, and signed 32-bit WASAPI mix
  formats are decoded into clamped float32 samples.
- `AudioNormalizer` performs arithmetic-mean channel downmix followed by a
  stateful linear interpolating resampler to 16 kHz mono. It preserves fractional
  phase across capture packets and rejects a mid-stream format mutation.
- There is no loudness normalization, DC removal, anti-aliasing resampler,
  channel-correlation policy, limiter, or denoiser.
- Rust sends 1,600-sample (100 ms) signed-16/base64 audio messages to the worker.

### Queues and threads

- WASAPI capture runs on its own thread and never blocks on inference. Its native
  frame queue has capacity 16.
- Rust-to-Python commands use a capacity-24 channel; Python audio uses a
  capacity-32 queue.
- VAD and ASR run on separate persistent Python threads. The ASR job queue has
  capacity two and coalesces superseded partials; a final may evict queued work.
- Worker events use a capacity-128 Rust channel. Runtime-to-desktop events also
  use capacity 128. Both currently drop an event indiscriminately when full.
- Capture, worker-audio, and ASR coalescing counters exist. Queue latency and ASR
  queue depth are not directly measured.

### VAD and streaming segmentation

- The worker uses the Silero ONNX session vendored inside faster-whisper 1.2.1,
  described in code as Silero v6. The asset has no independent revision/hash or
  license record in this repository.
- VAD consumes 512 samples (32 ms) with 64 samples of recurrent context.
- Current defaults are speech threshold 0.50, two positive frames to start,
  400 ms pre-roll, end threshold 0.35, 450 ms end silence, 800 ms partial
  interval, and an 8 s maximum utterance.
- A partial repeatedly decodes all accumulated audio in the current utterance.
  A VAD end or the 8 s cap submits the same accumulated audio as a final. The
  cap starts a new independent VAD segment rather than maintaining confirmed
  audio/text context across the forced boundary.

### ASR, language identification, and translation

- One persistent faster-whisper 1.2.1 `WhisperModel` handles language detection,
  recognition, and translation.
- Profile-to-model mapping is `fast -> base`, `balanced -> small`, and
  `accurate -> medium`. The packaged default is multilingual `small` from
  `Systran/faster-whisper-small`, cache revision
  `536b0662742c02347bc0e980a01041f333bce120`.
- Partials use greedy decoding (`beam_size=1`); finals use `beam_size=3`.
  Temperature is zero and previous-text conditioning is disabled. Only English
  receives a bounded English `initial_prompt`.
- The language detector evaluates up to 8 s. A final decays accumulated scores,
  tracks repeated candidates, and creates a stable language after one strong
  sufficiently long result or two consistent results. Stable language is reused
  for partials. Twelve seconds of inferred silence resets it; two confident
  contradictory finals can switch it.
- English uses Whisper `task="transcribe"`. Every non-English language uses
  Whisper `task="translate"` directly to English.
- Russian, Japanese, and Hindi therefore have the same route. There is no stable
  source-language transcript, text MT engine, IndicTrans2 path, per-language
  router, or direct-vs-cascade comparison.
- The worker emits log probability, no-speech probability, compression ratio,
  LID confidence, inference duration, and RTF. Hallucination guards combine
  those signals with empty-output, repetition, and recent-output checks.

### Model loading and hardware fallback

- Packaged model resolution is relative to the executable and requires a
  complete local faster-whisper cache snapshot. Development can download a
  named model through faster-whisper.
- AUTO tries CUDA/float16 when CTranslate2 reports a CUDA device, then CPU/int8.
  It keeps NVIDIA wheel DLL directories alive with `os.add_dll_directory`.
- A one-second silent English transcription and Russian direct-translation
  decode serve as warmup/backend smoke tests before capture begins.
- The existing evidence was collected on an RTX 4060 with 8,188 MiB VRAM;
  current inspection confirms the same GPU. There is no CPU/RAM/GPU profile
  object, sustained hardware microbenchmark, DirectML route, or automatic
  headroom decision.

### Subtitle stabilization and overlay

- `SubtitleAssembler` owns display state. It rejects stale revisions, lets
  extension-like partials replace the current tentative text, holds major
  partial rewrites until final, removes exact normalized overlaps of at least
  three words between final segments, and keeps a bounded 500-segment in-memory
  history.
- Tentative/final state exists internally, but the normal overlay displays both
  with the same visual treatment. A weak first partial can remain visible until
  final because incompatible revisions are withheld.
- Source text is always `None`. Only the English output is retained.
- Line layout targets two 44-character lines, but overlong text is discarded
  from the front and marked with an ellipsis. That can remove meaning.
- Four seconds after a final, the runtime sends a clear event. It does not clear
  the assembler's internal `current` value at that point.

### Installer and distribution

- Inno Setup creates a per-user Windows x64 installer named
  `LiveSub-0.1.0-win64.exe`. The existing artifact is 1,469,884,555 bytes.
- The offline payload bundles the Rust executable, an embeddable Python 3.12
  runtime, exact Python/CTranslate2/CUDA packages, the Python worker, and the
  faster-whisper `small` model. The installed app does not require system Python,
  Node, Rust, FFmpeg, or a CUDA toolkit.
- The package is not digitally signed. It has no online/resumable model download
  manager, disk-space gate, signed registry, language-pack manifest, pack
  signature, promotion/rollback flow, or option to retain models on uninstall.
- Python packages are version-pinned for the Windows runtime, but hashes are not
  pinned. The model is copied from a Hugging Face cache; the installer does not
  validate a production manifest at installation time.

### Tests and existing evidence

- Baseline on this audit: Rust unit tests pass 9/9 and the Python protocol
  self-test passes.
- Rust tests cover PCM quantization, basic resampling/format mutation,
  subtitle revision/overlap/layout behavior, simple LID adaptation, and overlay
  alpha conversion.
- The Python self-test covers PCM decode, partial coalescing, repetition checks,
  task routing, local-model resolution failure, and long-silence LID reset.
- Existing artifacts demonstrate real WASAPI capture, silence/music VAD smoke
  tests, installed CUDA and CPU fallback, transparent overlay, Russian YouTube,
  and a three-minute Russian run. They do not contain a human-aligned golden
  corpus and cannot produce WER, CER, COMET, chrF++, critical-word recall, or
  statistically meaningful hallucination rates.
- Existing Japanese and Hindi runs are explicitly recorded as mixed quality.
  No Qwen3-ASR, Whisper large-v3, specialist MT, 30-minute-per-language run,
  fourth-language install, signed registry, or clean-machine test of the future
  online language-pack flow has been performed.

## CURRENT ACCURACY BOTTLENECKS

1. The only production result is direct Whisper translation with the `small`
   model. It prevents independent ASR/MT measurement and discards diagnostically
   valuable source text.
2. There is no `ASREngine` or translation-provider contract, so model comparison
   and language-specific routing are not product architecture yet.
3. There is no golden-corpus manifest, reference transcript, semantic English
   reference, critical-term annotation, metric runner, or evidence-based model
   selection gate.
4. The final pass is merely a higher-beam decode of the same capped utterance.
   It has no stronger per-language engine, confirmed source context, glossary,
   or independent translation/verification pass.
5. Streaming stability is revision filtering, not LocalAgreement-style token
   confirmation. Forced 8 s cuts lose boundary context; exact three-word overlap
   removal misses morphological/paraphrased overlap.
6. Linear downsampling provides no explicit anti-alias filtering. Arithmetic
   downmix can attenuate phase-opposed speech. Neither choice has an A/B corpus.
7. VAD provenance and tuning are not independently pinned or benchmarked.
   Thresholds are global and most are not configurable through the protocol.
8. LID is coupled to Whisper and exposes only the selected candidate rather than
   a distribution. Reset/switch behavior has limited acceptance coverage.
9. Hallucination checks are useful but heuristic. There is no audio-energy field
   on inference jobs, segment-level duplicate-rate metric, or per-language false
   positive/false negative VAD scorecard.
10. There is no terminology engine, confidence-based session glossary,
    translation memory, or automated semantic checks for negation, numbers,
    directions, names, time, currency, and percentages.
11. The UI exposes implementation labels (`fast`, `balanced`, `accurate`) rather
    than verified `Maximum Accuracy`, `Balanced`, and `Low Resource` profiles.
    It has no bilingual mode or language management.
12. Model provenance, license due diligence, artifact hashes, registry signing,
    safe download, local acceptance, updates, and rollback are absent.

## PROPOSED CHANGES

The changes are ordered to obtain evidence before changing the verified live
route.

1. Add a versioned corpus/evaluation schema and offline benchmark CLI. It will
   retain audio references, human source text, semantic English, tags, critical
   terms, and consent/license metadata; compute WER/CER, chrF++, BLEU as a
   secondary metric, critical-error counts, LID accuracy, latency percentiles,
   RTF, duplicates, and hallucinations; and leave COMET explicitly unavailable
   unless its reviewed evaluator is installed.
2. Introduce capability-described ASR and translation provider interfaces at the
   worker boundary. Keep the current faster-whisper implementation as the
   compatibility engine, then add benchmark adapters for Whisper large-v3 and
   Qwen3-ASR 0.6B/1.7B without enabling either in production by default.
3. Change inference records to preserve source transcript and English
   translation independently. Benchmark direct translation against source-ASR
   plus reviewed text MT per language before selecting a route.
4. Implement explicit tentative/confirmed hypotheses using repeated-prefix/token
   agreement, bounded source/audio context, VAD finals, and overlap reconciliation.
   Retain the existing assembler behind compatibility tests during migration.
5. Add critical-meaning checks, terminology preservation, a confidence/repetition
   gated session glossary, and context-sensitive translation memory.
6. Add a versioned `LanguagePack` manifest and curated local registry with exact
   revisions, hashes, licenses, hardware recipes, acceptance gates, atomic
   activation, previous-pack retention, and rollback. Registry signing and
   network download must fail closed until keys/endpoints are production-owned.
7. Add hardware inventory plus a sustained RTF/headroom benchmark and map results
   to Maximum Accuracy, Balanced, or Low Resource. A model is READY only after
   warmup and a successful runtime check.
8. Upgrade audio conditioning or VAD defaults only after A/B evaluation. In
   particular, benchmark a band-limited resampler and independently pinned
   current Silero VAD against the existing implementation; keep denoising off by
   default.
9. Add the language library, settings persistence, bilingual option, first-run
   progress, and developer diagnostics after the underlying states are real.
10. Move distribution toward a small application installer plus verified,
    resumable default-pack setup. Keep the existing offline installer as a
    rollback path until clean-machine acceptance passes.

## EXPECTED BENEFIT

- Source ASR errors and translation errors become independently measurable and
  debuggable per language.
- Russian, Japanese, and Hindi can select different evidence-backed routes rather
  than sharing the weakest common denominator.
- Dual-pass recognition and agreement-based confirmation should improve names,
  endings, numbers, code switching, punctuation, and subtitle stability while
  preserving a bounded live delay.
- Critical-meaning checks and terminology state target errors that matter more
  than cosmetic fluency.
- A signed, pinned language-pack recipe makes model delivery reproducible,
  reviewable, rollback-safe, and supportable.
- Hardware headroom measurement avoids both needlessly weak models and a queue
  that slowly falls behind realtime.

These are hypotheses until the new harness records results. No candidate model is
called a winner in this audit.

## RISK OF REGRESSION

| Change area | Primary regression risk | Required containment |
|---|---|---|
| ASR/MT routing | Wrong task, language, or stale cross-language context | Compatibility provider, per-language golden gates, explicit route metadata |
| Dual pass | Final jobs starve streaming work or exceed live latency | Separate bounded priorities, p50/p95/RTF gates, cancellation/coalescing |
| Confirmation | Missing words or excessive subtitle delay | Token-alignment fixtures and live revision/commit latency tests |
| Audio conditioning | Resampler/downmix damages speech | Bit-exact fixtures plus per-language A/B WER/CER |
| VAD tuning | Quiet speech is cut or music hallucinates text | Speech/noise false-negative and false-positive corpora |
| Glossary/memory | An uncertain name becomes persistent corruption | Confidence/repetition thresholds, expiry, context checks, user reset |
| Language packs | Partial/corrupt/unlicensed model becomes active | Staging, hash/license verification, atomic promote, rollback |
| Installer | Clean machines miss a runtime or cannot recover downloads | Offline rollback build and clean-machine installation matrix |
| Existing live path | WASAPI/overlay stability is accidentally rewritten | Preserve native capture/overlay components and rerun existing real-audio tests |

The current application remains a valid compatibility baseline, not an
accuracy-first release candidate.
