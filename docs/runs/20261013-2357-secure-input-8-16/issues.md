# #8 [P0][macOS] Spike: Touch ID and Secure Input detection / Touch ID と Secure Input 検知 [OPEN]
Roadmap decisions 10 and 11.

## Tasks
- [ ] Call `LocalAuthentication` (`LAContext.evaluatePolicy`, biometrics with password fallback) from the py2app bundle via PyObjC; confirm it works from the menu bar app process
- [ ] Confirm the behaviour on Macs without Touch ID (password fallback)
- [ ] Call `IsSecureEventInputEnabled()` (Carbon) from the capture loop; confirm it turns true for password fields in Safari, Chrome and a native app, and false otherwise
- [ ] Measure the call cost per capture

## Done when
A written go/no-go and a minimal code sketch for each API.

## 日本語

ロードマップの決定10・11。

### タスク
- [ ] py2app のバンドルから PyObjC 経由で `LocalAuthentication`（`LAContext.evaluatePolicy`、生体認証とパスワードによる代替）を呼び、メニューバーアプリのプロセスから動くことを確認する
- [ ] Touch ID のない Mac での挙動（パスワードによる代替）を確認する
- [ ] キャプチャのループから `IsSecureEventInputEnabled()`（Carbon）を呼び、Safari・Chrome・ネイティブアプリのパスワード欄で true、それ以外で false になることを確認する
- [ ] キャプチャ1回あたりの呼び出しコストを測定する

### 完了条件
API ごとに、実施可否（go / no-go）と最小限のコード例が文書化されていること。
---comments---
@ikeikeikeda66 2026-09-26T08:24:58Z
### Touch ID probe (#8)

- macOS 15.7.4, arm64, Python 3.12.13
- Process: `/Users/ikedashinichi/ScreenContext/.venv/bin/python` (inside an .app bundle: False)

| Policy | Available | Biometry | Success | Error | Seconds |
|---|---|---|---|---|---|
| owner | True | touch_id | True | - | 4.4 |
| biometrics | False | touch_id | - | other (com.apple.LocalAuthentication -12) | - |

Note: `biometrics` policy reports `available: False` with error code -12, which isn't in the probe's `ERRORS` map (shows as "other"). `owner` policy succeeded normally (password fallback allowed).

### Secure Input probe (#8)

- macOS 15.7.4, arm64
- `IsSecureEventInputEnabled()` cost: 0.09 µs per call
- Transitions: 9
- True for more than 30s in a row while frontmost: none

| Frontmost app | Samples true | Samples false |
|---|---|---|
| com.anthropic.claudefordesktop | 0 | 190 |
| com.apple.Passwords | 103 | 10 |
| com.apple.Safari | 34 | 164 |
| com.apple.systempreferences | 0 | 115 |
| com.google.Chrome | 24 | 189 |

Scenarios exercised: Safari password field, Chrome password field (twice), com.apple.Passwords app, System Settings. No stuck app (nothing stayed `true` for more than 30s while frontmost).
---
@ikeikeikeda66 2026-09-26T09:08:39Z
Correction on the earlier Touch ID result: error `-12` is not undefined — it's `LAErrorBiometryNotPaired` from LocalAuthentication's own `LAError` enum. The probe's `ERRORS` map only covered `-1..-10`, so it showed as "other". Not a pyobjc or Apple bug, just a gap in `touchid_probe.py`.

Fixed in commit ccb8f42 (adds `-11` companionNotAvailable, `-12` biometryNotPaired, `-13` biometryDisconnected, `-14` invalidDimensions to `ERRORS`).

So the corrected `biometrics` row from the earlier run:

| Policy | Available | Biometry | Success | Error | Seconds |
|---|---|---|---|---|---|
| biometrics | False | touch_id | - | biometryNotPaired (com.apple.LocalAuthentication -12) | - |

Worth noting for whoever revisits #8: `biometryNotPaired` on a Mac with Touch ID enrolled and working (the `owner` policy succeeded) is unexpected and may be worth investigating on its own — possibly Secure Enclave / biometric pairing state specific to the `biometrics`-only policy path.
# #16 [P1][macOS] Skip capture while Secure Input is on / Secure Input 中はキャプチャしない [OPEN]
Roadmap decision 11. Depends on the Phase 0 Touch ID / Secure Input spike.

## Tasks
- [ ] Before each capture, check `IsSecureEventInputEnabled()`; if true, capture nothing (no spool file)
- [ ] Record the skip in the capture status and the skip counter (category `secure_input`)
- [ ] Platform function behind the existing platform interface so Windows can plug in its own

## Tests
- [ ] Fake platform returning true/false; no spool file when true

## 日本語

ロードマップの決定11。フェーズ0の Touch ID / Secure Input の技術検証が前提。

### タスク
- [ ] 毎回のキャプチャ前に `IsSecureEventInputEnabled()` を確認し、true なら何もキャプチャしない（スプールファイルも作らない）
- [ ] スキップしたことを、キャプチャの状態と除外件数（カテゴリ `secure_input`）に記録する
- [ ] 既存のプラットフォームのインターフェースの裏に実装し、Windows が独自の実装を差し込めるようにする

### テスト
- [ ] true/false を返す偽のプラットフォームを使い、true のときスプールファイルが作られないことを確認する
---comments---

