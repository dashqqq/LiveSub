# Silero VAD A/B decision — 2026-08-22

## Decision

**HOLD. Do not replace the packaged VAD in the live application yet.**

Silero VAD 6.2.1 was integrated behind the benchmark interface and tested with
the same ASR engine and decoder policy as the packaged faster-whisper VAD. It
is a valid pinned candidate, but this small corpus does not demonstrate an
accuracy improvement. The production default remains unchanged.

## Compared implementations

| Implementation | SHA-256 | Runtime interface |
| --- | --- | --- |
| faster-whisper 1.2.1 packaged `silero_vad_v6.onnx` | `4cbf549b8326f60f80f2536d9eefeb450a9abe83365a098031c89719f1be17d2` | legacy `input`, `h`, `c` |
| Silero VAD 6.2.1, upstream commit `7e30209a3e901f9842f81b225f3e93d8199902b1` | `1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3` | current `input`, `state`, `sr` with the required 64-sample context |

Both used speech threshold 0.50, end threshold 0.35, minimum silence 450 ms,
speech padding 400 ms, 16 kHz mono audio, current faster-whisper-small, beam 3,
segment timestamps, and a 128-token decoder cap.

## Results

| Language / fixture | VAD | Speech segments | Speech coverage | p50 ASR | p95 ASR | RTF | Decoder loops |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Japanese practice | Packaged | 14 | 57.84% | 177.5 ms | 213.75 ms | 0.142 | 0 |
| Japanese practice | 6.2.1 | 14 | 60.11% | 187 ms | 210.15 ms | 0.137 | 0 |
| Russian dialogue | Packaged | 5 | 99.79% | 205 ms | 337.4 ms | 0.063 | 0 |
| Russian dialogue | 6.2.1 | 4 | 99.97% | 238.5 ms | 358.9 ms | 0.057 | 0 |
| Hindi speech | Packaged | 41 | 93.99% | 348 ms | 824 ms | 0.139 | 1 |
| Hindi speech | 6.2.1 | 41 | 93.97% | 428 ms | 842 ms | 0.157 | 1 |

The Japanese transcript was identical between implementations. In the Russian
dialogue, the 6.2.1 segmentation merged one boundary and the resulting ASR text
lost the short token `А` before `меня`. Hindi did not improve: segment count and
decoder-loop count were unchanged while p50 latency and RTF regressed.

## Evidence and limitations

Raw records are the matching
`benchmark-current-*-live-vad-{packaged-policy-corrected,silero-6.2.1-context-corrected}-20260822.jsonl`
files in this directory. Each record contains the VAD model path, hash, tuning,
speech boundaries, per-segment output, latency, RTF, and loop flags.

This is not a VAD acceptance corpus. It lacks human-labelled speech boundaries,
quiet speech, music-only negatives, explosions, keyboard noise, overlapping
speakers, and equal-volume A/B fixtures. Promotion remains blocked until those
cases measure false-positive speech, false-negative speech, boundary clipping,
hallucination rate, and downstream ASR/translation quality.
