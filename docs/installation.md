# Installing LiveSub Preview

LiveSub is a 64-bit Windows desktop application. The public installer is distributed as a GitHub Release asset, not committed to the source repository.

## Availability

**LiveSub v0.1.0 Preview is publicly available** on its [GitHub pre-release page](https://github.com/dashqqq/LiveSub/releases/tag/v0.1.0). Use that version-specific page during the Preview phase; GitHub's `/releases/latest` route is reserved for stable releases and may not select a pre-release.

## Install

1. Open the [LiveSub v0.1.0 Preview release](https://github.com/dashqqq/LiveSub/releases/tag/v0.1.0).
2. Confirm that the release is marked **Pre-release**.
3. Download `LiveSub-Setup.exe` and `LiveSub-Setup.exe.sha256`.
4. Verify the checksum using the command below.
5. Run `LiveSub-Setup.exe` and complete the per-user installation.
6. Open **LiveSub** from the Start menu.

```powershell
Get-FileHash -Algorithm SHA256 .\LiveSub-Setup.exe
Get-Content .\LiveSub-Setup.exe.sha256
```

The two hashes must match exactly. Do not run an installer whose checksum does not match the checksum asset on the same GitHub Release.

## Windows SmartScreen

LiveSub Preview does not yet have a commercial code-signing certificate. Windows may therefore identify it as an unknown publisher or show a reputation warning. Code signing is a stable-release gate.

Do not disable Microsoft Defender, SmartScreen, or another security product to install LiveSub. If Windows or your organization blocks unsigned applications, wait for a signed release.

## What the installer contains

The current self-contained installer design includes:

- the native LiveSub Windows application;
- a private Python 3.12 inference runtime;
- the bundled faster-whisper-compatible multilingual model;
- CUDA inference libraries used when compatible hardware is available;
- CPU fallback;
- required native media/runtime libraries.

It is designed so an end user does not install Python, Node.js, Rust, FFmpeg, the CUDA Toolkit, or build tools manually. LiveSub does not install an NVIDIA display driver.

## Storage and connectivity

The reviewed v0.1.0 Preview artifact is 1,453,494,708 bytes with SHA-256 `be81ef997f4a2e467e68d4d651481b73a24b8dacdaf5494c184f3e1df9e724a5`. Its measured installed payload is approximately 2.67 GiB. Leave additional temporary space for installer extraction.

The self-contained Preview build does not need an internet connection for normal translation after installation. Downloading the installer itself requires internet access. Future Language Packs may be separate verified downloads.

## Uninstall

Use **Settings → Apps → Installed apps → LiveSub → Uninstall**. The current Preview does not yet implement the final user choice for retaining separately downloaded Language Packs because the consumer Language Library is not released.
