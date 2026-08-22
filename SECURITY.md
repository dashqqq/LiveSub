# Security policy

## Supported versions

LiveSub is currently a Preview and has no stable supported release line. Security fixes will be evaluated against the latest published Preview when releases begin.

## Report a vulnerability privately

Open the repository’s [Security page](https://github.com/dashqqq/LiveSub/security) and use **Report a vulnerability** if private vulnerability reporting is enabled.

If that route is unavailable, open a public issue containing only a request for a private contact channel. Do not include exploit details, credentials, private audio/transcripts, secrets, or proof-of-concept code in that public issue.

Include privately:

- affected LiveSub version or commit;
- Windows version and relevant hardware;
- concise impact and reproduction steps;
- whether audio, transcripts, model files, update/download integrity, installer behavior, or privilege boundaries are involved;
- any suggested mitigation.

Please allow reasonable time to reproduce and prepare a fix before public disclosure.

## Scope priorities

High-priority areas include WASAPI/audio data exposure, transcript leakage, unsafe model loading, registry/signature/hash bypass, arbitrary code execution, installer tampering, privilege escalation, dependency supply-chain issues, and unapproved network transmission.
