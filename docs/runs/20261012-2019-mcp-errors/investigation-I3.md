# I3 報告（要約、証拠確認済み: service.py:313,315 / runner.py:40）
実測: 23件中22件 UnexpectedToolError（理由なし）。get_daily_rollup date="2026-9-1" は通る（緩い）。day_range("9999-12-31") は OverflowError。get_day_material 9999-12-31 は service.py:184-185 で素の ValueError。
分類: 入力→InvalidArgument: service.py L17,18,93,173,179,181,198,266,280,300,307,313、runner.py L40,107,108,112,114,116,120,123,124（関数内 import で循環回避）。
内部のまま: L35(Unknown profile), L125(require_full, MCP 到達不能), L315(Invalid image path), L176/262/264(try 内制御)。
day_range 厳格化: strptime + 往復一致、except (ValueError, OverflowError, OSError, TypeError) → InvalidArgument("date must use YYYY-MM-DD")。
get_day_material L184-185 を try、→ InvalidArgument("date or timezone is invalid")。
任意: decode_cursor の cursor_key() を try 外へ。→ 今回は見送り（スコープ外、挙動変更）。
未対応（別判断）: get_current_screen の broker PermissionError/TimeoutError は UnexpectedToolError のまま。
i18n: エラー文言は既存どおり英語直書き（service/access/runner）。i18n 不要と判断。
テスト I3-S2: tests/test_core.py に BAD_INPUTS parametrize、UnexpectedToolError でないこと＋理由文字列、除外と不存在の同一文言、Invalid image path は UnexpectedToolError、正常 date 成功。
