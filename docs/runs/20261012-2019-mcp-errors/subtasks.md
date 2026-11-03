# 実装サブタスク（TDD: テスト先 → 失敗確認 → 実装）
T1 tests/test_mcp_errors.py 新規 + tests/test_http.py 追記（I2-S2,S2-3）
T2 tests/test_core.py 追記（I3-S2）
C1 service.py: InvalidArgument 定義・bounded・get_activity_between・I3-S1 置換・day_range 厳格化・get_day_material L184-185 / runner.py 置換 / mcp_server.py guarded（I2-S1+I3-S1）。decode_cursor の cursor_key 移動は見送り。
調停: 「包括 catch していない」証拠は Invalid image path（内部扱い）で確認。空 query は変換対象。
