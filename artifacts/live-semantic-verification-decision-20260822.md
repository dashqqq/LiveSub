# Live semantic verification measurement — 2026-08-22

## Decision

**Keep the bounded conditional verification policy enabled for further
evaluation. Do not call it accuracy-validated yet.**

The live benchmark route runs the current faster-whisper-small direct English
pass, an independent source transcript, and a beam-5 translation retry only
when reference-free semantic checks find a critical/high issue. The retry is
selected only when its `(critical, high, total)` issue tuple is strictly lower.

## Runtime results

Test host: Windows, NVIDIA RTX 4060, CUDA float16. VAD and decoder policy match
the live worker. Language was forced from each manifest so these measurements
do not count as LID evidence.

| Language / fixture | Segments | p50 total inference | p95 total inference | RTF | Checks | Retry selected | Final runtime issues | Decoder loops |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Russian dialogue, current small | 5 | 263 ms | 654 ms | 0.105 | 2 | 0 | 2 | 0 |
| Japanese practice, current small | 14 | 191 ms | 221.1 ms | 0.153 | 0 | 0 | 0 | 0 |
| Hindi speech, current small | 41 | 338 ms | 1,119 ms | 0.138 | 6 | 2 | 4 | 1 |
| Russian dialogue, large-v3 | 5 | 825 ms | 1,434.2 ms | 0.281 | 1 | 0 | 1 | 0 |
| Japanese practice, large-v3 | 14 | 653 ms | 1,001.5 ms | 0.561 | 0 | 0 | 0 | 0 |
| Hindi speech, large-v3 | 41 | 1,042 ms | 2,033 ms | 0.376 | 1 | 0 | 1 | 0 |

The Russian retries were rejected because they did not reduce the completeness
issue count. The two selected Hindi retries reduced completeness issue counts;
one Hindi repetition loop and four semantic heuristic issues remain. No retry
was required for the Japanese fixture.

Large-v3 reduced the reference-free issue count on the Russian and Hindi
fixtures and eliminated the Hindi decoder-loop flag. It remained below RTF 1
for all three languages, with p95 inference at or below 2.033 seconds. Device-
level VRAM was approximately 5,079 MB, versus 1,942 MB for current small. These
figures make large-v3 viable for the human-gold and sustained-live gates on this
GPU; they do not prove that its text is more accurate.

## Evidence

- `benchmark-current-ru-dialog-live-policy-verified-20260822.jsonl`
- `benchmark-current-ja-live-policy-verified-20260822.jsonl`
- `benchmark-current-hi-live-policy-verified-20260822.jsonl`
- `benchmark-whisper-large-v3-ru-dialog-live-policy-verified-20260822.jsonl`
- `benchmark-whisper-large-v3-ja-live-policy-verified-20260822.jsonl`
- `benchmark-whisper-large-v3-hi-live-policy-verified-20260822.jsonl`

Each segment records direct, source, and verification inference time; initial
and final quality reports; selection; model/VAD identity; RAM/VRAM; RTF; and
decoder-loop flags.

## Gate still blocked

All three fixtures remain `pending_human_review`. Therefore WER, CER, chrF++,
COMET, and human semantic preference are unavailable, and the two selected
Hindi changes cannot yet be claimed as genuine accuracy improvements. The
policy passes the live latency constraint on this host and is eligible for the
human-gold regression gate; it has not passed that gate.
