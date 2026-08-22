# Senior accuracy and release review — 2026-08-22

This review covers the implemented accuracy campaign, the live Rust/Python
boundary, subtitle presentation, model staging, language-pack activation, and
the offline Windows installer. It distinguishes source/test findings from
release gates that still require external evidence.

## Findings fixed

1. **Critical translations could enter session memory.** A fluent direct result
   with a missing negation, number, direction, currency, percentage, or required
   term could previously be cached. Memory admission now requires a completely
   clean semantic report; a selected stronger correction may replace a prior
   hit. Regression tests cover both acceptance and rejection.
2. **Worker control events could become protocol-incompatible.** Transcript-only
   fields now deserialize with defaults, and a minimal `hello` event has a Rust
   regression test. This prevents a harmless worker schema addition from making
   an installed worker appear silent.
3. **Non-ASCII source finals failed on a Windows legacy code page.** Worker
   protocol output is explicitly UTF-8, while diagnostic stderr escapes
   unencodable characters. Installed Russian/Japanese/Hindi playback verified
   the corrected path.
4. **Long subtitle layout discarded leading words.** Layout now preserves the
   entire English result and balances it across the requested display lines.
   The overlay reduces font size when necessary instead of truncating meaning.
5. **Tentative and confirmed subtitles looked identical.** Tentative output now
   uses a softer text tone; confirmed output remains the high-contrast state.
6. **A stalled UI could preferentially lose a final transcript.** Both bounded
   handoffs now give confirmed/error/ready events a bounded 250 ms delivery
   opportunity while ordinary partial/diagnostic traffic remains drop-safe.
   Worker event drops are counted and visible in developer diagnostics.
7. **The packaged worker was incomplete and locale-fragile.** Packaging now
   includes LID/language-pack modules, exposes the application root to embedded
   Python, ships Ed25519 dependencies, and validates exact inference/security
   imports before compiling the installer.
8. **Consumer execution could implicitly resolve an online model.** Normal app
   execution is local-only and fails clearly when a verified model is absent.
   Only an explicit development command can opt into model download.
9. **Language-pack activation accepted insufficient provenance.** Production
   registries require exact revisions and artifact sets; packs reject extra,
   missing, linked/reparse, wrong-size, or wrong-hash files and retain rollback
   state across failed promotion.
10. **A newer VAD candidate had an incorrect recurrent-context integration in
    the first A/B run.** The official 64-sample context behavior was corrected,
    the comparison rerun, and Silero 6.2.1 was held because no accuracy benefit
    was demonstrated and Hindi latency regressed.

## Configuration review

- No `large-v3-turbo` final translation route exists.
- Direct non-English Whisper decoding uses `task="translate"`; the independent
  source final uses `task="transcribe"`.
- Direct translation never receives prior English as non-English decoder
  context. Source context is language-scoped and bounded.
- All queues are bounded. Audio capture and ASR submission remain non-blocking;
  superseded partial jobs coalesce instead of accumulating an inference backlog.
- Final and source decodes have bounded token counts. Semantic verification is
  limited to one stronger beam-5 pass.
- Qwen and Transformers adapters set `trust_remote_code=False`. Production pack
  validation rejects any recipe that requires remote code.
- The default installed route remains the known-working faster-whisper `small`
  route. Large-v3 is a measured candidate, not a production winner.

## Verification performed after fixes

- Python unit tests: 39 passed.
- Rust unit tests: 12 passed.
- `cargo check`, formatting, and Clippy with warnings denied passed.
- Private embedded-Python inference/security import smoke passed in packaging.
- Fresh installed CUDA warmup, worker protocol, WASAPI loopback, and real
  Russian/Japanese/Hindi system-audio paths passed before the last small source
  refinements. The final post-review installer was then rebuilt and passed
  byte-identity checks, protocol/security/UTF-8 smoke, CUDA float16 warmup, a
  real Russian WASAPI run with four finals and zero drops, and native-overlay
  visual inspection. Japanese and Hindi were not fully replayed after the final
  source-only refinements.

## Unresolved release blockers

1. Zero corpus cases have human-approved source and semantic-English references,
   so WER, CER, chrF++, COMET, semantic accuracy, and final per-language model
   selection cannot be claimed.
2. Qwen3-ASR 0.6B/1.7B, Whisper large-v3, and the current engine were exercised,
   but forced-language runtime evidence is not an LID accuracy benchmark.
3. OPUS/M2M cascade candidates produced runtime semantic failures. IndicTrans2
   1B remains gated and remote-code-dependent; no reviewed Hindi specialist
   route is production-approved.
4. The short Hindi installed test began with a low-confidence Russian candidate
   before Hindi locked. This needs corpus-backed LID tuning, not a hard-coded
   exception.
5. Streaming uses VAD-bounded repeated-window partials plus stable-prefix
   replacement and final correction. It does not yet implement token-level
   LocalAgreement/AlignAtt confirmation across forced eight-second boundaries.
6. The session glossary is conservative and primarily observes ASCII-form
   proper nouns. It does not yet prove consistent non-Latin name transliteration.
7. The curated registry is development-unsigned and therefore correctly fails
   closed in production mode. No production key, controlled registry endpoint,
   or signed release pack exists.
8. Language-pack security/rollback infrastructure exists, but it is not wired to
   a consumer Language Library/download UI. No fourth language has passed an
   end-to-end install and acceptance flow.
9. Hardware-profile UI/selection, first-run setup, online resumable default-pack
   delivery, pack retention during uninstall, tray behavior, and app/model
   update separation are not complete.
10. There is no 30-minute continuous run for each default language, no full
    acceptance matrix, and no repository-absent clean-machine/VM certification.
11. The offline installer and app are not code-signed. The Inno 6.7.3 compiler
    used for this validation build reported `Non-commercial use only`; resolving
    its commercial-use status (license activation or documented legal approval)
    and rebuilding remain a distribution compliance gate.
12. The offline installer still ships the small universal route because stronger
    routes are not evidence-selected.

These blockers require measured evidence or product integration; relabeling the
current profiles or promoting a model would conceal rather than resolve them.
