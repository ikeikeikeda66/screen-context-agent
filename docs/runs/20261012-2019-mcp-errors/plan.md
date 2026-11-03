# 調査計画（investigation-planner ab39093546d191626 の要約）
I1: PR #78 検証（P1,P2）。一時 worktree、standard/full の生 tools/list 表、hints と挙動の一致、PR/main の全 pytest。修正は作らず PR レビュー案のみ。
I2: 変換の仕組み（P3,P4）。guarded は常にラップ。service.py に InvalidArgument(ValueError) を定義し、mcp_server はそれだけ ToolError 化。PermissionError 変換範囲は不変。functools.wraps 維持。
  S2-1 guarded+定義 / S2-2 tests/test_mcp_errors.py（stdio 実プロセス + authorize=None 直接、逆順・同値・7日超・NaN/Inf、traceback なし、回帰）/ S2-3 test_http.py
I3: 他ツールの raise 棚卸し・分類（P5）。S3-1 raise を InvalidArgument に置換、S3-2 test_core.py parametrize。
順序: 調査並列、実装は S2-1→S2-2→S2-3→S3-1→S3-2 直列。ブランチ fix/mcp-input-errors-69（main 2e473d1 起点）。test_integration.py・CHANGELOG は #78 と衝突回避。
オーケストレータ判断: エラー文言はエージェント向け英語。既存 service.py の ValueError 文言も英語直書きなので i18n には載せない（I3 で既存扱いを確認）。push/PR 作成はユーザー確認後。
