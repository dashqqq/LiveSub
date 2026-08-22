# LiveSub release process

Application releases and future Language Pack releases are separate. A small application update must not force users to redownload unrelated model weights.

## Current public status

Version `0.1.0` is reserved for a **Preview** pre-release. The current engineering verdict is **ACCURACY-FIRST RELEASE: NOT READY**. Do not create `v1.0.0`, label this build stable, or publish an unreviewed binary automatically from a tag.

The installer is prepared locally, but public binary release is blocked until:

1. the project owner supplies/approves the root source license (Cargo metadata currently says MIT, but no `LICENSE` file exists);
2. Inno Setup commercial-use status is resolved for the actual release process;
3. bundled model, Python, native library, media/codec, CUDA, and notice obligations are reviewed;
4. the release asset and checksum are revalidated immediately before upload.

Code signing, full accuracy certification, long-run testing, and repository-absent clean-machine certification remain stable-release gates. An honest pre-release may disclose those open validation gates after legal redistribution clearance.

## Installer-tooling review

The current packaging script invokes Inno Setup. The compiler used during the reviewed build identified itself as a non-commercial installation. Inno Setup’s official pages ask commercial users to purchase a license and describe commercial licensing terms:

- [Inno Setup overview](https://jrsoftware.org/isinfo.php)
- [Commercial licenses](https://jrsoftware.org/isorder.php)
- [License purchase terms](https://jrsoftware.org/isorder-terms.php)

Those upstream statements do not by themselves establish LiveSub’s legal clearance. Before a commercial public release, the owner must document the appropriate Inno Setup license/approval and rebuild the artifact with the approved tooling. Do not claim clearance based only on the installer compiling successfully.

## Required release gates

| Gate | Preview | Stable |
| --- | --- | --- |
| Correct repository and reviewed commit | Required | Required |
| Native/Python tests and lint | Required | Required |
| Secret/private-data scan | Required | Required |
| Installer package/import smoke test | Required | Required |
| SHA-256 generated from final artifact | Required | Required |
| Source and bundled-component license review | Required | Required |
| Marked pre-release and limitations disclosed | Required | Not applicable |
| Human-reviewed language accuracy acceptance | Disclose if open | Required |
| Long-run per-language validation | Disclose if open | Required |
| Repository-absent clean-machine validation | Disclose if open | Required |
| Code signing | Disclose if open | Required |
| Manual release approval | Required | Required |

## Prepare a Preview

1. Run the commands in [development.md](development.md).
2. Run real WASAPI, media, and overlay checks appropriate to the changed scope.
3. Review the staged Git diff and scan exactly the staged publication set for secrets and private paths.
4. Build `dist/LiveSub-Setup.exe` from the reviewed commit.
5. Install into an isolated location and run packaged inference/import smoke tests.
6. Recalculate SHA-256 with `Get-FileHash -Algorithm SHA256 .\dist\LiveSub-Setup.exe` and update the checksum asset.
7. Confirm the checksum file and installer size against the final artifact.
8. Create annotated tag `v0.1.0` only after the exact commit is approved.
9. Create a **draft pre-release** named **LiveSub v0.1.0 Preview**.
10. Upload `LiveSub-Setup.exe` and `LiveSub-Setup.exe.sha256`; never add the executable to Git history.
11. Verify the uploaded asset size and checksum, all release links, release notes, and pre-release flag.
12. Publish only after manual approval.

Tagging and publishing are deliberately not automated merely because a tag exists. A future workflow may build, test, and package an artifact, but release promotion must remain gated by accuracy, security, licensing, and clean-machine evidence.

## Rollback

Do not overwrite release assets in place. If a Preview is invalid, mark it clearly, remove it from the preferred download path, and publish a corrected version/tag. Keep previous known-good Language Packs until candidates pass integrity, accuracy, latency, stability, and hardware acceptance.

## Repository metadata

- **Description:** Accuracy-first live English subtitles for Windows system audio. Russian, Japanese and Hindi.
- **Topics:** `live-subtitles`, `speech-recognition`, `translation`, `windows`, `asr`, `accessibility`, `real-time`, `russian`, `japanese`, `hindi`
- **Website:** leave empty until an official site exists.
- **Private vulnerability reporting:** enabled.
