# LiveSub accuracy scorecard

Selection ready: **NO**

Missing values are shown as `N/A`; they are never inferred from model claims.

## ru

| Engine / route | WER | CER | LID | chrF++ | Gold critical | Runtime QA | Loops | p50 | p95 | RTF | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| current-faster-whisper-small / source_asr | N/A | N/A | 1.000 | N/A | N/A | N/A | 0.000 | 242.000 ms | 404.000 ms | 0.078 | NO |
| qwen3-asr-0.6b / source_asr | N/A | N/A | 1.000 | N/A | N/A | N/A | 0.000 | 1659.000 ms | 2976.800 ms | 0.506 | NO |
| qwen3-asr-1.7b / source_asr | N/A | N/A | 1.000 | N/A | N/A | N/A | 0.000 | 1935.000 ms | 3519.800 ms | 0.580 | NO |
| whisper-large-v3 / direct_translation | N/A | N/A | N/A | N/A | N/A | N/A | 0.013 | 510.000 ms | 948.200 ms | 0.135 | NO |
| whisper-large-v3 / source_asr | N/A | N/A | N/A | N/A | N/A | N/A | 0.004 | 620.000 ms | 1080.600 ms | 0.149 | NO |
| whisper-large-v3+opus-mt-ru-en / asr_then_mt | N/A | N/A | N/A | N/A | N/A | 54/229 | 0.022 | 779.000 ms | 1375.200 ms | 0.188 | NO |

## ja

| Engine / route | WER | CER | LID | chrF++ | Gold critical | Runtime QA | Loops | p50 | p95 | RTF | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| current-faster-whisper-small / source_asr | N/A | N/A | 1.000 | N/A | N/A | N/A | 0.000 | 190.500 ms | 204.850 ms | 0.147 | NO |
| qwen3-asr-0.6b / source_asr | N/A | N/A | 1.000 | N/A | N/A | N/A | 0.000 | 606.000 ms | 703.350 ms | 0.481 | NO |
| qwen3-asr-1.7b / source_asr | N/A | N/A | 1.000 | N/A | N/A | N/A | 0.000 | 465.500 ms | 578.300 ms | 0.370 | NO |
| whisper-large-v3 / direct_translation | N/A | N/A | N/A | N/A | N/A | N/A | 0.000 | 334.500 ms | 353.700 ms | 0.262 | NO |
| whisper-large-v3 / source_asr | N/A | N/A | N/A | N/A | N/A | N/A | 0.000 | 330.500 ms | 346.950 ms | 0.257 | NO |
| whisper-large-v3+opus-mt-ja-en / asr_then_mt | N/A | N/A | N/A | N/A | N/A | 0/14 | 0.000 | 377.000 ms | 409.200 ms | 0.294 | NO |

## hi

| Engine / route | WER | CER | LID | chrF++ | Gold critical | Runtime QA | Loops | p50 | p95 | RTF | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| current-faster-whisper-small / source_asr | N/A | N/A | 1.000 | N/A | N/A | N/A | 0.098 | 463.000 ms | 4261.000 ms | 0.293 | NO |
| qwen3-asr-0.6b / source_asr | N/A | N/A | 1.000 | N/A | N/A | N/A | 0.000 | 2354.000 ms | 7291.000 ms | 0.880 | NO |
| qwen3-asr-1.7b / source_asr | N/A | N/A | 1.000 | N/A | N/A | N/A | 0.000 | 3791.000 ms | 13903.000 ms | 1.455 | NO |
| whisper-large-v3 / direct_translation | N/A | N/A | N/A | N/A | N/A | N/A | 0.000 | 848.000 ms | 1425.000 ms | 0.288 | NO |
| whisper-large-v3 / source_asr | N/A | N/A | N/A | N/A | N/A | N/A | 0.000 | 652.000 ms | 1240.000 ms | 0.230 | NO |
| whisper-large-v3+m2m100-418m / asr_then_mt | N/A | N/A | N/A | N/A | N/A | 5/41 | 0.024 | 789.000 ms | 1486.000 ms | 0.284 | NO |

## Corpus gates

- hi: 0/1 human-approved; missing tags: code_switching, fast, gaming, livestream, multiple_speakers, music, noise, numbers; ready: NO
- ja: 0/1 human-approved; missing tags: code_switching, fast, gaming, livestream, multiple_speakers, music, names, noise, numbers; ready: NO
- ru: 0/4 human-approved; missing tags: code_switching, gaming, livestream, music, noise; ready: NO
