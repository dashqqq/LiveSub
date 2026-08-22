# Accuracy at LiveSub

LiveSub is intended to produce subtitles people can trust, not merely text that arrives quickly. Accuracy is evaluated as a pipeline property: audio capture, speech boundaries, language identification, source transcription, translation, critical-token preservation, and subtitle stability can each introduce a different error.

## What is implemented

The current engineering build includes:

- stateful 16 kHz mono audio conditioning before inference;
- Silero voice activity detection with pre-roll so speech boundaries retain context;
- accumulated language evidence, hysteresis, a stable lock, and silence reset;
- fast rolling partial recognition and an independent final source-language pass;
- source context separated by language;
- direct speech-to-English translation plus an optional specialist text-translation route;
- terminology matching, a confidence/repetition-based session glossary, and context-aware translation memory;
- checks for negation, numbers, directions, time, currency, percentages, and configured terminology;
- no-speech, confidence, compression, energy, and repetition suppression;
- overlapping-window deduplication and tentative/final subtitle revisions;
- bounded audio, worker, and UI queues with drop/coalescing diagnostics.

The current bundled Preview route uses the faster-whisper-compatible `small` multilingual model. Candidate adapters and registry entries for stronger engines exist for evaluation, but a candidate is not a production route merely because it is present in the repository.

## How candidates are compared

ASR is evaluated per language with:

- word error rate (WER) where word boundaries are meaningful;
- character error rate (CER), especially for Japanese and script-sensitive cases;
- language-identification accuracy;
- proper-name, number, terminology, and code-switch correctness;
- noisy-speech and hallucination behavior;
- real-time factor (RTF), p50/p95 latency, RAM, and VRAM.

Translation is evaluated with multiple signals:

- human-reviewed semantic English references;
- COMET or COMETKiwi-style scoring where the evaluator can be run safely;
- chrF++ and BLEU as supporting, not sole, metrics;
- critical-error checks for lost or changed negation, quantities, directions, names, time, currency, and percentages;
- consistency, duplicate rate, meaning preservation, and human review.

Results must remain separate for Russian, Japanese, and Hindi. One multilingual average cannot justify the production route for all three.

## Golden corpus policy

The repository contains corpus manifests and validation schemas for Russian, Japanese, and Hindi. A releasable golden corpus must cover clean speech, casual and fast speech, livestreams, games, code switching, names, numbers, noise/music, and multiple speakers. Hindi evaluation must explicitly include Hinglish.

Human-reviewed audio/reference pairs are not yet included in the public repository. Consequently, the project does not publish unfinished metric values as product claims, and the accuracy certification gate remains open.

## Runtime acceptance gates

A model that improves offline accuracy can still be rejected from a live profile if it cannot sustain real time or creates unacceptable subtitle delay, memory pressure, or instability. The target experience is approximately two to four seconds of perceived latency on capable hardware, with occasional additional finalization time for difficult phrases.

A candidate route is promoted only after it improves accuracy without violating explicit live-runtime gates. Newer model names and README claims are not evidence.

## Current status

| Area | Status |
| --- | --- |
| Benchmark harness and schemas | Implemented |
| Runtime semantic/critical-token checks | Implemented |
| Streaming stabilization and bounded queues | Implemented |
| Russian/Japanese/Hindi corpus manifests | Implemented, references not human-approved |
| Full per-language ASR/translation benchmark matrix | Under evaluation |
| Human-reviewed public scorecards | Not complete |
| Thirty-minute real-stream tests per default language | Not complete |
| Evidence-selected production route per language | Not complete |

Detailed engineering evidence is retained in [accuracy-verification-20260822.md](accuracy-verification-20260822.md), [accuracy-audit.md](accuracy-audit.md), and [senior-review-20260822.md](senior-review-20260822.md). Those documents are verification records, not marketing certifications.
