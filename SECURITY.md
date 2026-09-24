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
- Bypassing bearer authentication on the HTTP transport

Out of scope: prompt injection through screen text itself. Results are labeled untrusted, but that label cannot neutralize instructions shown on screen; clients must treat screen text as data.
