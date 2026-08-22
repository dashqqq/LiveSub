# LiveSub privacy

This document describes the current repository implementation. It is not a promise about hypothetical future cloud features.

## Audio capture

LiveSub uses Windows WASAPI loopback to capture audio being rendered by the selected output device. Normal system-audio translation does not require microphone access. The runtime downmixes and resamples captured frames, then passes them through bounded in-memory queues to the local inference worker.

The current runtime does not write captured audio to disk. Audio is retained only as bounded working buffers and recent context needed for speech boundaries, language identification, and final recognition.

## Transcripts and subtitles

Source transcripts and English translations are held in memory for the active session. The subtitle assembler keeps a bounded in-memory history for display consistency. The current application does not persist transcript history to a database or transcript file.

Diagnostic fields include stage timings, language codes and confidence, model/backend labels, queue depths, audio levels, drop counts, RTF, and quality-check status. The current application writes ordinary process diagnostics to standard error; it does not have transcript telemetry or a remote analytics service.

## Local processing

The current packaged translation route runs locally. It has no cloud ASR/translation provider and does not upload raw audio by default. There is no platform-specific YouTube, Twitch, Discord, or browser API integration in the live path.

## Internet access

Normal execution does not implicitly download a missing model. Network access is used by explicit development/setup and curated model-staging tools, which download selected model files and record provenance locally. The current application has no automatic update checker.

Future Language Pack downloads or optional online-enhanced providers must distinguish their network use from local translation. Any feature that sends audio or transcript content to a service must be opt-in and disclose the destination, purpose, retention implications, and cost before use.

## Public bug reports

Do not attach private conversations, copyrighted recordings, credentials, or personally identifying media to a public GitHub issue. A short, self-created sample may be attached only when the reporter has the right and informed consent to share it. Text descriptions are sufficient for most reports.
