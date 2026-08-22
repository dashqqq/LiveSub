# LiveSub benchmark harness

This directory is the evidence boundary for accuracy decisions. A model card is
not a benchmark result. Prediction records are scored only against cases whose
`gold_status` is `human_approved` and that contain both a source transcript and
a semantic English reference.

The pre-existing repository audio has been registered as
`pending_human_review`. This is intentional: model-generated text is not silently
promoted to gold. Strict validation currently fails and therefore prevents a
model from being selected on fabricated metrics.

## Commands

```powershell
python benchmarks/evaluate.py validate
python benchmarks/evaluate.py validate --strict
python benchmarks/evaluate.py score --predictions artifacts/predictions.jsonl `
  --output-json artifacts/scorecard.json `
  --output-markdown artifacts/scorecard.md
python benchmarks/run_asr.py --engine current --language ru `
  --route source_asr --output artifacts/current-source-asr.jsonl
python benchmarks/run_asr.py --engine whisper-large-v3 --language ru `
  --route live --final-beam-size 3 --force-manifest-language `
  --model-path models/staged/whisper-large-v3/<pinned-revision> `
  --model-revision <pinned-revision> --output artifacts/large-v3-live-verified-ru.jsonl
python benchmarks/run_translation.py `
  --input artifacts/current-source-asr.jsonl `
  --engine opus-mt-ru-en `
  --model-path models/staged/opus-mt-ru-en `
  --model-revision fbd6dc73284f95536648512cc21d57f19191961a `
  --output artifacts/current-plus-opus-ru.jsonl
python -m unittest discover -s benchmarks/tests
```

Core WER, CER, LID accuracy, latency, RTF, duplicate/repetition, and critical
meaning checks have no third-party dependency. Install
`requirements-metrics.txt` to add pinned SacreBLEU BLEU and chrF++.

COMET is deliberately reported as unavailable until a specific evaluator model
has passed license/provenance review and its revision/hash is configured. The
harness never downloads evaluator weights as a side effect of scoring.

The ASR runner is local-only by default. Qwen candidates require an explicit
staged `--model-path` and exact `--model-revision`; Whisper large-v3 resolves a
complete local cache snapshot or accepts the same explicit pair. Add
`--allow-download` only in a controlled model-staging workflow, never in the
consumer live process.

The `live` route reproduces the accuracy policy rather than measuring a single
decoder call: beam-3 direct English, an independent source-language final pass,
then a bounded beam-5 retry only when the semantic guards find a critical/high
issue. The record includes both candidates' quality reports, whether the retry
was selected, and all added inference time in latency/RTF.

The translation runner consumes the recognizer's actual source transcript. It
does not replace ASR output with gold text. Its `latency_ms` and `rtf` include
both passes, while separate ASR and MT timings remain in metadata.

Candidate-only Python runtimes can be isolated from the shipped worker by
setting `LIVESUB_BENCHMARK_PACKAGE_ROOT` to a reviewed local package directory.
The runner inserts that exact directory into `sys.path`; ordinary live worker
startup never reads it.

## Prediction record

Each line is JSON matching `schema/prediction.schema.json`. Required identity
fields are `case_id`, `engine_id`, `model_id`, and `route`. Runtime fields such as
latency, RTF, RAM, and VRAM are measurements from the same inference invocation,
not values copied from a README.
