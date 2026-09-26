# Phase 0 spikes

[日本語](#日本語)

Manual probes for Phase 0 of [docs/ROADMAP.md](../../docs/ROADMAP.md). They run on real hardware only. None of them captures the screen or reads your history. Each prints a Markdown block to paste into its issue. Do not commit the output: it names the apps on your machine. `spike-results/` is ignored by git.

Run everything from the repository root after `uv sync --locked --extra macos --extra encrypted --extra dev` (or `--extra windows`).

## macOS

### #7 Screen Recording grant with a fixed self-signed identity

```sh
sh spikes/phase0/macos/signing_spike.sh identity   # once; macOS asks for your password to trust the certificate
sh spikes/phase0/macos/signing_spike.sh build v1
open dist/ScreenContext.app                        # grant Screen Recording, then quit and open again
.venv/bin/screen-context index --watch &           # optional; `check` only needs the capture app
sh spikes/phase0/macos/signing_spike.sh check      # expect permission: unknown, capture: spooled or excluded
# quit the app
sh spikes/phase0/macos/signing_spike.sh build v2   # a new build with a different code hash
open dist/ScreenContext.app                        # do NOT grant again; note any Keychain prompt
sh spikes/phase0/macos/signing_spike.sh check      # permission_error = the grant was lost
sh spikes/phase0/macos/signing_spike.sh compare v1 v2
sh spikes/phase0/macos/signing_spike.sh dmg v2     # Gatekeeper first-launch test from a quarantined DMG
```

Paste the `compare` block and the two `check` lines into #7, plus: Keychain prompt on v2 (yes/no), the Gatekeeper steps you saw, and go/no-go. If `codesign --timestamp` fails with the self-signed identity, note it; the build script then needs `--timestamp=none` for local builds.

### #8 Touch ID and Secure Input

```sh
uv pip install --python .venv/bin/python pyobjc-framework-LocalAuthentication
.venv/bin/python spikes/phase0/macos/touchid_probe.py              # one prompt per policy
.venv/bin/python spikes/phase0/macos/secure_input_probe.py --seconds 180
```

The Secure Input probe lists scenarios to try while it runs. Watch for apps that keep the flag on after you leave the field ("stuck"): Secure Input is global, so one stuck app would pause capture everywhere.

## Windows

### #6 Current beta on real hardware

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
.venv\Scripts\python.exe spikes\phase0\windows\env_report.py
```

Paste the report into #6, then walk the checklist it prints and fill in each result. File a bug issue for each failure.

### #9 Windows Hello and password-field detection

```powershell
uv pip install --python .venv\Scripts\python.exe winrt-Windows.Security.Credentials.UI comtypes
.venv\Scripts\python.exe spikes\phase0\windows\hello_probe.py
.venv\Scripts\python.exe spikes\phase0\windows\uia_password_probe.py --seconds 180
```

Fill in the two blanks in the Hello report (prompt in front, fallback without Hello).

---

## 日本語

[docs/ROADMAP.ja.md](../../docs/ROADMAP.ja.md) のフェーズ0で使う、手動で実行する検証スクリプトです。実機でのみ動きます。どれも画面のキャプチャや履歴の読み取りは行いません。各スクリプトは、対応する Issue にそのまま貼れる Markdown を出力します。出力には PC 内のアプリ名が含まれるため、コミットしないでください（`spike-results/` は git の管理対象外です）。

事前に `uv sync --locked --extra macos --extra encrypted --extra dev`（Windows は `--extra windows`）を実行し、リポジトリのルートから実行します。

### macOS

- **#7 自己署名での画面収録許可の維持**：上の英語の手順どおりに実行します。`build v1` → 許可 → `check` → `build v2` → **許可し直さずに**起動 → `check` → `compare` → `dmg`。`compare` の出力、2回分の `check` の結果、v2 起動時に Keychain の確認ダイアログが出たか、Gatekeeper で表示された手順、実施可否（go / no-go）を #7 に貼ります。自己署名で `codesign --timestamp` が失敗した場合は、その旨も記録します（ローカルビルドでは `--timestamp=none` が必要になります）。
- **#8 Touch ID と Secure Input**：`touchid_probe.py` はポリシーごとに1回ずつ認証ダイアログを出します。`secure_input_probe.py` は、実行中に試す操作を画面に表示します。入力欄を離れても true のまま戻らない（stuck）アプリがないか確認してください。Secure Input は OS 全体のフラグなので、1つのアプリが戻らないと、すべてのアプリでキャプチャが止まります。

### Windows

- **#6 現行ベータの実機検証**：`build_windows.ps1` でビルドし、`env_report.py` の出力を #6 に貼ります。出力されたチェックリストを順に確認して結果を記入し、不合格の項目ごとにバグ Issue を起票します。
- **#9 Windows Hello とパスワード欄の検知**：`hello_probe.py` の出力の空欄2か所（ダイアログが前面に出たか、Hello 未設定時の代替手段）を記入します。`uia_password_probe.py` は、実行中に試す操作を画面に表示します。
