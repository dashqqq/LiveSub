# LiveSub accuracy scorecard

Selection ready: **NO**

Missing values are shown as `N/A`; they are never inferred from model claims.

## ru

| Engine / route | WER | CER | LID | chrF++ | Gold critical | Runtime QA | Loops | p50 | p95 | RTF | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| current-faster-whisper-small / live | N/A | N/A | N/A | N/A | N/A | 2/5 | 0.000 | 263.000 ms | 654.000 ms | 0.105 | NO |
| whisper-large-v3 / live | N/A | N/A | N/A | N/A | N/A | 1/5 | 0.000 | 825.000 ms | 1434.200 ms | 0.281 | NO |

## ja

| Engine / route | WER | CER | LID | chrF++ | Gold critical | Runtime QA | Loops | p50 | p95 | RTF | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| current-faster-whisper-small / live | N/A | N/A | N/A | N/A | N/A | 0/14 | 0.000 | 191.000 ms | 221.100 ms | 0.153 | NO |
| whisper-large-v3 / live | N/A | N/A | N/A | N/A | N/A | 0/14 | 0.000 | 653.000 ms | 1001.500 ms | 0.561 | NO |

## hi

| Engine / route | WER | CER | LID | chrF++ | Gold critical | Runtime QA | Loops | p50 | p95 | RTF | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| current-faster-whisper-small / live | N/A | N/A | N/A | N/A | N/A | 4/41 | 0.024 | 338.000 ms | 1119.000 ms | 0.138 | NO |
| whisper-large-v3 / live | N/A | N/A | N/A | N/A | N/A | 1/41 | 0.000 | 1042.000 ms | 2033.000 ms | 0.376 | NO |

## Corpus gates

- hi: 0/1 human-approved; missing tags: code_switching, fast, gaming, livestream, multiple_speakers, music, noise, numbers; ready: NO
- ja: 0/1 human-approved; missing tags: code_switching, fast, gaming, livestream, multiple_speakers, music, names, noise, numbers; ready: NO
- ru: 0/4 human-approved; missing tags: code_switching, gaming, livestream, music, noise; ready: NO
