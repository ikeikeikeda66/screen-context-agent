# I2 報告（要約、証拠確認済み: mcp_server.py:15、SDK base.py:205-210、server.py:436-445）
再現: 逆順・同値・7日超・NaN/Infinity(生 JSON リテラル) すべて (a)直接 (b)実 stdio (c)HTTP で "Error executing tool get_activity_between" のみ、stderr に Traceback。非有限は bounded の isfinite で既に ValueError → bounded も InvalidArgument 化が必要。
修正: guarded を常にラップ（authorize None なら CURRENT_CLIENT を触らない）。except InvalidArgument → ToolError のみ。wraps でスキーマ不変（実測一致）。
SDK は ToolError を "Error executing tool X: <reason>" にし logger.info（traceback なし）。
テスト注意: server.call_tool 直接は SDK ログを通らない → caplog は mcp.Client(server) in-memory か実 stdio で。
