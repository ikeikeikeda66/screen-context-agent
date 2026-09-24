$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run this script on Windows.' }
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (!(Test-Path $PythonExe)) { throw 'Create .venv and install the Windows dependencies first.' }
Push-Location $ProjectRoot
try {
    & $PythonExe -c 'import tkinter, windows_capture, sqlcipher3.dbapi2, keyring.backends.Windows; from winrt.windows.media.ocr import OcrEngine'
    if ($LASTEXITCODE -ne 0) { throw 'Packaging dependencies are missing.' }
    & $PythonExe -c "import inspect; from windows_capture import WindowsCapture; assert 'window_hwnd' in inspect.signature(WindowsCapture).parameters, 'Exact HWND capture is required'"
    if ($LASTEXITCODE -ne 0) { throw 'A windows-capture version with window_hwnd support is required.' }
    $Common = @('--noconfirm', '--clean', '--onedir', '--distpath', 'dist/windows', '--workpath', 'build/windows', '--specpath', 'build/windows', '--collect-all', 'screen_context', '--collect-all', 'windows_capture', '--collect-all', 'winrt', '--collect-all', 'sqlcipher3', '--hidden-import', 'keyring.backends.Windows', '--hidden-import', '_cffi_backend')
    & $PythonExe -m PyInstaller @Common --windowed --name ScreenContext packaging/windows_main.py
    if ($LASTEXITCODE -ne 0) { throw 'GUI build failed' }
    & $PythonExe -m PyInstaller @Common --console --name screen-context packaging/windows_cli.py
    if ($LASTEXITCODE -ne 0) { throw 'MCP CLI build failed' }
    & $PythonExe packaging/verify_windows.py
    if ($LASTEXITCODE -ne 0) { throw 'Bundle verification failed' }
} finally { Pop-Location }
