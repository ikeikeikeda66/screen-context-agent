# Security Policy

ScreenContext stores images and text from your screen. Please report vulnerabilities privately.

## Reporting

Use GitHub's private vulnerability reporting ("Report a vulnerability" in the Security tab of this repository). Do not open a public issue for security problems.

Include the affected version or commit, your OS, steps to reproduce, and the impact.

## Scope

In scope, for example:

- Reading history without the encryption key, or bypassing exclusions (`policy.json`) on any read path
- Raising the profile of an MCP server process, or reaching `full` tools from `standard`
- Capturing without the per-call approval in `get_current_screen`
- Bypassing client-token authentication (stdio or HTTP), the profile ceiling, or revocation

## Known limits

These are documented design limits, not vulnerabilities (see the threat model in the README):

- Programs running as the same user can read the history: they can copy a client token from its configuration file or read the key from the credential store.
- A self-signed macOS build disables library validation (`packaging/entitlements.plist`), because the embedded Python.framework cannot load without it. A program running as the same user could therefore plant a library in the app and use its Screen Recording permission. A Developer ID build would not need the entitlement.
- A local administrator can bypass managed settings.
- Exports and results already returned to clients are outside the encrypted store.
- Sensitive-input detection is pattern based and depends on OCR.

Out of scope: prompt injection through screen text itself. Results are labeled untrusted, but that label cannot neutralize instructions shown on screen; clients must treat screen text as data.
