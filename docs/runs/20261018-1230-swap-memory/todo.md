# swap-memory run

依頼: 起動中のscreencontextが2日間でメモリのスワップ領域を48GB使用していた。原因調査し、メモリスワップをさせないように改修して。issue起票してから実施して。

予算: サブエージェント合計12体まで、実装→検証やり直しはサブタスクごと2回まで。

- [x] 0 準備・実測（rss-samples.txt）
- [x] 1 調査計画 plan.md
- [x] 2 調査 investigation-I<n>.md + 証拠確認
- [x] 2.5 issue 起票 #98
- [x] 3 実装
- [x] 4 検証 test-<ID>.md
- [x] 5 レビュー report.md
- [ ] 6 コミット・PR

実装（branch fix/98-autorelease-pool）並列:
- A I2-S1/S2 indexer.py native_ocr + tests/test_ocr_memory.py
- B I1-S1/S3 mac_app.py CocoaStop.wait + platforms/macos.py foreground/capture + tests
- C I4-S1/S2 memory.py + desktop.py Workers.poll 上限再起動 + tests
見送り: I1-S2(refresh 変化検出), I1-S4, I3-S1, I4-S3(i18n), I4-S4(親PID監視, 取り残し証拠なし)
