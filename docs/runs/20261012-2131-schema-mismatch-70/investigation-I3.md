# I3 要約（証拠確認: mcp_server.py:117-118, indexer.py:103-104）
実測: stdio v3/v9 起動時 Traceback exit1。ツール実行中 UnexpectedToolError。HTTP 500。案(b)プロトタイプで tools/list 13、tools/call isError+案内、rc0、Traceback なし。
F3-1 guarded(function, authorize, settings) で authorize/function の SchemaMismatch → ToolError(schema_message)。F3-2 run stdio で authenticate の SchemaMismatch を stderr 1行にして起動継続。F3-3 BearerGate 503 → ユーザー未選択のため保留。
別 issue 候補: maintain の24h spool 削除（既存設計、不一致中に未索引フレーム喪失）、desktop worker 再起動使い切り、windows_app 起動ダイアログ、ui/ui_views。
