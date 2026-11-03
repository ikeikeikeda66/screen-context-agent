# test-runner 結果（A/B/C まとめ）
1 全件 pytest: 692 passed, 0 failed
2 対象サブセット: 58 passed
3 autorelease_pool: indexer.py 1, mac_app.py 2, macos.py 2
4 回帰: indexer.py の変更を stash すると test_ocr_memory.py が 3 failed。pop で復元済み
5 mcp_server.py / memory.py に objc/AppKit/Quartz の import 0件
6 変更範囲は指定ファイルのみ
