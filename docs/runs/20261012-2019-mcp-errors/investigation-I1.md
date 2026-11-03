# I1 報告（要約、証拠確認済み: PR mcp_server.py:63-66、worktree 削除済み）
結論: go。main と PR で tools/list の hints は同一。実 stdio・合成環境で standard(5)/full(13) とも全ツール4 hints が bool。
表: 読み取り系 T/F/T/F、submit_proposal F/F/T/F、get_current_screen F/F/F/F。挙動と一致（読み取り系の監査行は bookkeeping、submit_proposal は24h重複抑止で概ね冪等）。
pytest: PR 471 passed / main 469 passed（PR 本文の「465 passed, 4 skipped」と不一致）。
変異: M1/M2/M3 は PR テストで検出。M4（openWorld 反転）は PR の2テストは通るが、既存 tests/test_core.py:148-152 が値を検証しているので全体では検出される（オーケストレータ確認）。
レビュー案: S1-1 stdio テストを standard/full でパラメータ化 / S1-2 値照合（test_core で既にあり、優先度低）/ S1-3 submit_proposal の idempotent 根拠コメント / S1-4 PR 本文の件数修正。
残る外部条件: マージ後 M8ven 再スキャン。ループ登録11ツールはスキャナに見えない（解析上の制約）。
