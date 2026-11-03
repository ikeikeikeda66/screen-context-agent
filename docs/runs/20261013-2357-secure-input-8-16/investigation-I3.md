# I3 要約
store.record_skip(settings, category, day=None): DB なしは False（connect が空ファイルを作るため）、except Exception（sqlcipher3.Error は sqlite3.Error 派生でない）、CAPTURE_SKIPS=("secure_input",)。7.4ms/回（plaintext）、撮影周期ごと（既定15秒）。
誤表示: ui_views.skipped が「個人情報の可能性」、status_text が「処理済み」。修正: i18n status.secure_input / ui.skip.secure_input（en/ja）、desktop.status_text、ui_views.skipped で CAPTURE_SKIPS を dropped 扱い。review は ID 表記のまま。health/MCP は last_status に secure_input が出るだけで内容なし。
