# 調査計画（investigation-planner 要約、証拠確認済み store.py:109-110,122 / lifecycle.py:68 / health.py:133）
共通IF: store.SchemaMismatch(RuntimeError) found/expected/newer。connect と migrate で送出。str は英語で "schema version" を含む。
i18n: schema.outdated / schema.newer（{found}{expected}{db}）、schema_message(error, lang)。
I1 store/init/backup/restore/health: F1-1 例外、F1-2 initialize の未来版無変更、F1-3 古い DB の backup、F1-4 restore 未来版拒否、F1-5 health 区別、F1-6 tests/test_migrations.py
I2 CLI/i18n/文書: F2-1 i18n、F2-2 cli main 一括捕捉 exit 1、F2-3 tests/test_cli_schema.py、F2-4 README/CHANGELOG
I3 MCP: F3-1 guarded、F3-2 stdio 起動、F3-3 BearerGate 503、F3-4 tests、F3-5 他利用者の影響報告
順序: F1-1 → F2-1 → 他。ファイル重複なし。

## ユーザー決定（2026-10-12）
- stdio serve: 起動を続け、tools/call ごとに案内を ToolError で返す（データは返さない）
- backup: 古い DB でも可能にする（読み取り専用、manifest に実 schema）
- 範囲に含める: health 新状態 needs_newer_binary、restore の未来版拒否
- HTTP 503 は選ばれなかった → HTTP の BearerGate は今回変更しない（最終報告で確認事項として挙げる）
