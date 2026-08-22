# Contributing and feedback

LiveSub is in a focused Preview hardening phase. Public code contributions are not yet being solicited, because accuracy, packaging, licensing, and release evidence are changing together. Bug reports, reproducible translation problems, hardware results, and focused feature feedback are welcome.

## Before reporting

- Search existing issues for the same problem.
- Confirm the behavior on the newest available Preview.
- Record the LiveSub version, Windows version, CPU, GPU, RAM, and audio source/application.
- For translation reports, provide the source language, expected meaning, observed English subtitle, and whether speech was fast, noisy, overlapping, or code-switched.
- Include Diagnostics timing/queue values when relevant.

Do not post passwords, tokens, private conversations, personal paths, full logs containing sensitive information, or copyrighted media in a public issue. Audio is optional. Share only a short sample that you created or have explicit rights and consent to publish.

Use the structured forms:

- [Bug report](https://github.com/dashqqq/LiveSub/issues/new?template=bug_report.yml)
- [Translation problem](https://github.com/dashqqq/LiveSub/issues/new?template=translation_accuracy.yml)
- [Feature request](https://github.com/dashqqq/LiveSub/issues/new?template=feature_request.yml)

Security vulnerabilities follow [SECURITY.md](SECURITY.md), not the public bug form.

## Maintainer workflow

If the project owner requests a code contribution, follow [docs/development.md](docs/development.md). Changes that affect recognition, translation, VAD, language identification, or subtitle stability must include deterministic tests and identify the required per-language/live regression evidence. A model card or clean one-sentence sample is not sufficient acceptance evidence.

Keep generated models, installer payloads, private audio, logs, caches, browser profiles, and credentials out of Git. Do not enable arbitrary model remote code or introduce a network provider without an explicit privacy and security design.
