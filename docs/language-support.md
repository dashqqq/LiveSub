# Language support

LiveSub translates supported source speech into English. English input is transcribed as English captions.

## Current language set

| Language | Route in the current bundled Preview | Status |
| --- | --- | --- |
| Russian | Local speech recognition and English translation | Preview |
| Japanese | Local speech recognition and English translation | Preview |
| Hindi | Local speech recognition and English translation | Preview |
| English | Local English transcription | Supported |

The current bundled route uses a faster-whisper-compatible multilingual model. A final source-language transcription pass is preserved internally; for non-English segments the current default English output is Whisper direct translation unless a configured specialist translator passes verification.

The three default languages have exercised end-to-end engineering paths, but their human-reviewed accuracy certification is incomplete. “Preview” does not mean a published accuracy score or a stable language guarantee. Hindi/Hinglish, code switching, proper nouns, noisy media, and overlapping speakers remain important test areas.

## Automatic language detection

The detector accumulates up to several seconds of useful speech evidence, applies confidence/hit requirements, and uses hysteresis to avoid rapid language flipping. A stable language can reset after sustained silence or repeated contradictory evidence. A user-selected source-language override is also supported internally.

## Planned Language Packs

The repository includes a `LanguagePack` schema and a curated registry design. A production pack is intended to contain:

- exact language direction and display metadata;
- pinned ASR and translation routes;
- VAD and language-identification settings;
- hardware profiles and runtime compatibility;
- model owner, repository, revision, files, and SHA-256 hashes;
- upstream license and redistribution review;
- validation corpus version and benchmark results;
- signed-registry provenance, update, and rollback metadata.

Adding a language will not mean changing a dropdown or running arbitrary remote model code. Candidate files must come from an approved registry, be pinned and verified, pass local acceptance tests, and satisfy live latency/resource gates.

The consumer Language Library, signed production registry, end-to-end fourth-language proof, and update/rollback UI are not released yet. Candidate entries in `registry/` are development inputs, not a promise that their weights are bundled or approved for commercial distribution.
