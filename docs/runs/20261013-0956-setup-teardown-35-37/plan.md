# 計画要約（planner、事実は抜き取り確認）
clients.py: 書き込みなし、render のみ。cli mcp-config は毎回 access.issue（UPSERT で旧トークン失効、pending）。cli_command が clients と quick の2か所。mac_main.py は argv==1 で GUI。TOML 書き込みライブラリなし。
I1 35-A: Contents/MacOS/screen-context（symlink 推奨、署名前に build_mac.sh で作る）、mac_main で実行名 screen-context なら CLI・引数なし --help、cli_command 一本化、verify_bundle 検査
I2 35-B: 新 client_config.py（パス表 home 注入、JSON mcpServers/servers、TOML 行単位置換+tomllib 検証、バックアップ .screen-context-<日時>.bak 0600 最新5件、原子的書き込み、未対応は手動案内）、access に既存トークン判定、mcp-config --write [--dry-run]、tests/test_client_config.py（Path.home 差し替え autouse）
I3 35-C: onboarding.py 状態機械（権限・init・client）、mac_app 起動前に挿入、setup.* i18n
I4 37-A: uninstall.py plan/apply、cli uninstall [--wipe] [--confirm] [--dry-run]、順序（workers_stopped→設定削除→revoke→ログイン項目→旧 LaunchAgent→wipe→残るもの）
I5 37-B: メニュー（capture.lock を自分で持つので finally で解放後に apply）、二段階確認、文書
PR: 35-B → 35-A（並行可）→ 37-A → 35-C → 37-B

## ユーザー決定（2026-10-13）
- TOML: tomlkit を依存に追加（py2app 同梱も）
- トークン: 有効なら使い回す、無効なら再発行
- 撤去: screen-context の項目のみ自動、別名は一覧で選択
- ログ ~/Library/Logs/ScreenContext: 撤去で削除（画面内容が無いことを実装で確認）
- 推奨案採用: バックアップ最新5件・0600、シンボリックリンクはリンク先、JSONC は手動案内、Windows は #40
## 35-B 調査結果（I2）採用: Windsurf 手動、--force、失敗時 revoke のみ、VS Code 推定パス含める。tomlkit 0.15.1（MIT）。試作 scratchpad/s35/final/。
## 37-A 調査結果（I4）採用: 確認語 UNINSTALL / --wipe は ERASE、旧 LaunchAgent は .disabled 残し、loaded なら中止＋bootout 案内、失敗は続行記録、データフォルダ内 exports は wipe で消える旨を警告。lifecycle.wipe(locks=None)、client_config.remove_plan(also=())。試作 scratchpad/s37/（35-B レビュー修正前が基準）。ブランチは feat/client-config-35b の上に積む。
## 35-C 調査結果（I3）採用: setup.json の stage（init/clients/done）、既存 db ありは黙って done、権限拒否は request→案内→終了、init 失敗は stage 維持、client 選択はチェックボックス全オフ、メニュー「AI アシスタントを接続…」追加、conflict 文言は CLI と共通。試作 scratchpad/s35c/（737 passed）。積み順 35-B → 37-A → 35-C → 37-B。
