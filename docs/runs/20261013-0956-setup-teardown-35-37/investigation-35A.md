# 35-A 調査要約（証拠確認: py2app boot_app.py ARGVZERO、main.c setenv ARGVZERO）
相対シンボリックリンク Contents/MacOS/screen-context -> ScreenContext（build_mac.sh、署名前）。mac_main.plan(argv, name)：実行名 screen-context は常に CLI、引数なし --help。clients.cli_command のみ screen-context に変更（quick と indexer_workers は不変）。verify_bundle に検査追加。docs/MCP-CLIENTS.md 31行。
実機確認7項目（ビルド・リンク経由で Resources 解決・DMG 後もリンク保持・Keychain/TCC 再確認なし等）。
