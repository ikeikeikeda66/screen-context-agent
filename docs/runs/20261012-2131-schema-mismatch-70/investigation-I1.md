# I1 要約（証拠確認: lifecycle.py:87 audit.record, 108 unlink → 115 initialize）
実測: initialize(v9) は WAL でない DB だとヘッダ 18-19 が変わる（store.py:105）。snapshot は v3/v9 とも失敗。restore --replace 未来版は unlink 後に失敗。health は v3/v9 とも needs_init。
サブタスク: S1 SchemaMismatch(found, expected, newer)・connect/migrate で送出 / S2 peek_version で initialize 冒頭に未来版拒否 / S3 snapshot を readonly+migrating、version 返却、manifest schema 実値、不一致時 audit.record スキップ（要検討: 監査を落としてよいか）/ S4 restore で manifest schema > 現行を unlink 前に拒否 / S5 derive_state needs_newer_binary + NOT_CURRENT / S6 tests/test_migrations.py 7件
申し送り: docs/ARCHITECTURE.md:51「currently 3」が古い。
