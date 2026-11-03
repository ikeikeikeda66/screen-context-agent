# report #70
PR #82（fix/schema-mismatch-70、0da94f5）。552 passed。製品コードを戻すと新テスト失敗を確認。
レビュー major 2件（HTTP 500、maintain の spool 削除）→ 修正済み（503 はユーザー選択、maintain 先頭で DB 版確認）。
minor 対応: README の stdio/HTTP・init/restore 記述修正、backup の "audited": false。
未対応: peek_version の到達しない except（害なし）。暗号化 DB 実機未検証。
別 issue 候補: desktop worker の再起動上限、windows_app 起動ダイアログ、ui/ui_views の不一致表示。
制約違反: I2 調査者が capture --once を1回実行（一時ディレクトリ、削除済み、残存0件確認）。
