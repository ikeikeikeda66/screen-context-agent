# Contributing

Thank you for helping improve ScreenContext.

## Development setup

```sh
uv sync --locked --extra macos --extra encrypted --extra dev   # macOS
uv sync --locked --extra windows --extra encrypted --extra dev # Windows
.venv/bin/python -m pytest -q
```

Tests use temporary data folders, synthetic images and simulated OS APIs. They never capture your screen or read your history.

## Guidelines

- Keep the MCP server read-only (except the proposal outbox) and free of capture imports.
- Apply the current `policy.json` on every read path. A new exclusion must hide old data too.
- Never fall back to plaintext storage when encryption is unavailable.
- Do not log OCR text, window titles or query strings.
- Add user-visible text to both catalogs in `screen_context/i18n.py`.
- Add or update tests with each change.
- Test data must be synthetic. Do not commit real screenshots, OCR output or personal paths.

## Pull requests

Describe what changed and how you tested it, including the OS and version for platform code. Windows hardware test reports are especially welcome while Windows support is in beta.
