# Windows (beta)

The Windows version is **beta**. Capture, OCR and the control window are implemented and covered by automated tests that simulate the Windows APIs, but real-hardware testing is still limited. Please report problems, with your Windows version and display setup, in Issues.

## What the control window does

- **Start** checks the encrypted database, credential store and policy, then starts capture and OCR as two worker processes.
- **Pause / Resume Capture** stops and restarts new captures. Frames already in the spool are still indexed.
- **Stop** waits for OCR in progress, then stops both workers. If one worker exits unexpectedly, the other is stopped too.
- The last capture and OCR results are shown separately from whether the workers are running.
- **Language** switches all text in the window between System Default, English and 日本語.
- **Show MCP Client Setup** shows the entry for the selected MCP client, with absolute paths. It does not change any client configuration.
- Closing the window stops capture. Minimizing keeps it running. Tray icon and start at login are not implemented yet.
- A lock on the data folder prevents a second instance.

## Run from source

```powershell
uv sync --locked --extra windows --extra encrypted --extra dev
.venv\Scripts\python.exe -m screen_context.windows_app
```

Click **Start** the first time to initialize. The data folder is `%USERPROFILE%\.screen-context`, or `SCREEN_CONTEXT_HOME` if set. The encryption key is stored in Windows Credential Manager, keyed by the data folder path, so do not move the folder on its own.

The CLI works as on macOS:

```powershell
.venv\Scripts\screen-context init
.venv\Scripts\screen-context capture
# in another terminal
.venv\Scripts\screen-context index --watch
```

### OCR language

Windows OCR reads one language per engine. By default ScreenContext uses your Windows profile languages. To choose one, set `SCREEN_CONTEXT_OCR_LANGUAGES`, for example `ja-JP` or `en-US`. The matching OCR language capability must be installed (Settings > Time & language > Language & region > language options).

### Requirements

- Windows 10 or 11, x64. ARM64 is untested.
- Python 3.11+ (3.13 recommended for packaging).
- A `windows-capture` version that supports exact `window_hwnd` capture. Without it, capture stops rather than falling back to capture by title.
- Plaintext mode (`SCREEN_CONTEXT_PLAINTEXT=1`) is refused by the window.

## Portable build

PyInstaller does not cross-compile, so build on Windows:

```powershell
uv pip install --python .venv\Scripts\python.exe pyinstaller
powershell -File packaging\build_windows.ps1
```

Output:

```text
dist/windows/
  ScreenContext/ScreenContext.exe        control window
  screen-context/screen-context.exe      CLI and MCP server
```

Keep both folders under the same parent folder, with their bundled libraries. The control window generates MCP entries that point at the CLI next to it.

`build_windows.ps1` checks the dependencies, builds both executables, and runs `packaging/verify_windows.py`. The verifier uses a temporary data folder whose path contains spaces and non-ASCII characters and a temporary key. It checks encrypted initialization, `status`, and a stdio MCP session (tool list, a search, and refusal of image tools in the `standard` profile). It does not touch your screen or data.

There is no signed installer, auto-update or uninstaller yet. To update, quit the window and your MCP clients, then replace both folders. The data folder is outside the build folders and is kept.

## Acceptance checklist

Use this list when you test a build on real hardware:

1. First start creates an encrypted database and stores the key. After a restart, the same history opens.
2. Text shown in Chrome or Edge can be found with `search_screen_history`. Capture follows app switches.
3. Different languages, DPI changes, multiple monitors, closing windows, and lock/unlock never capture the wrong window.
4. While paused, no new captures are added; after resuming, capture works again. Stop and restart never duplicate workers.
5. If the OCR worker exits, capture stops too and the window shows the failure.
6. The window and CLI start from a path with spaces and non-ASCII characters, and an MCP client connects over stdio.
7. The frozen build does not spawn extra windows or processes, and closing the window ends all workers.
8. Credential Manager, NTFS permissions and code signing are checked before wider distribution.

Before and after each capture, ScreenContext compares the window handle, process ID, process start time and title, and discards the image if any changed. This does not detect content that changes inside the same window and title.
