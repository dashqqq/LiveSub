# LiveSub code-signing plan

LiveSub `0.1.0` Preview is currently unsigned. This does not change the
component redistribution analysis, but it does mean Windows can display an
**Unknown publisher** or SmartScreen warning. Users must not be instructed to
disable Defender, SmartScreen, or other security controls.

Code signing is required before a stable release. No self-signed certificate
will be presented as a public-trust solution.

## Practical signing routes

### Microsoft Artifact Signing

[Microsoft Artifact Signing](https://learn.microsoft.com/azure/artifact-signing/overview)
(formerly Trusted Signing) is a managed signing service. It provides managed
certificate lifecycle and HSM-protected keys, supports public-trust signing,
and signs a digest without uploading the complete artifact. Availability,
identity-validation eligibility, Azure subscription requirements, and service
region support must be confirmed for the actual LiveSub publisher before this
route is selected.

### Public Authenticode certificate

A standard or EV Authenticode certificate from a publicly trusted certificate
authority is also suitable. The publisher must complete the CA's identity
validation and satisfy its current private-key protection requirements. EV is
not treated as a substitute for secure release controls, nor is an unsupported
claim made that it will always bypass SmartScreen reputation checks.

Cloud signing or a hardware-backed key is preferred over placing an exportable
PFX and password in the repository or CI variables. The repository must never
contain a signing private key, certificate password, or access token.

## Required implementation

1. Establish the exact legal publisher identity. This is also needed to finish
   the root LiveSub source license.
2. Enroll that publisher with the selected signing provider.
3. Restrict signing permission to the protected release environment and the
   manually approved release job.
4. Build and test the final installer before signing it.
5. Sign `livesub.exe` and then the final `LiveSub-Setup.exe` with an RSA
   Authenticode certificate accepted by Windows.
6. Use SHA-256 for the file digest and an RFC 3161 timestamp with SHA-256.
7. Run `signtool verify /pa /all /v` against every signed executable.
8. Calculate and publish the SHA-256 only after signing, because signing changes
   the file bytes.
9. Install the downloaded public artifact and repeat the release smoke test.

Microsoft's [SignTool documentation](https://learn.microsoft.com/windows/win32/seccrypto/signtool)
requires explicit file and timestamp digest algorithms in current SDK builds
and recommends SHA-256. Microsoft's
[Smart App Control guidance](https://learn.microsoft.com/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)
currently calls for an RSA-based certificate from a trusted provider.

Illustrative commands, with the provider-specific certificate selection and
timestamp URL supplied by the release owner, are:

```powershell
signtool sign /fd SHA256 /tr <RFC3161-timestamp-url> /td SHA256 <file.exe>
signtool verify /pa /all /v <file.exe>
```

These placeholders are intentional. A signing provider and publisher identity
have not yet been selected, and the project must not publish copy-paste commands
that imply nonexistent credentials.

## Preview policy

An unsigned Preview may be published only after redistribution rights and all
Preview smoke/security gates pass. Its README and release notes must state:

> This Preview installer is currently unsigned. Windows SmartScreen may display
> an Unknown Publisher warning.

Code signing remains independent from accuracy certification and from the
license rights for every bundled component.
