# I3 調査報告（要約保存）
結論: Python 側（drain/maintain/失敗フレーム再処理/キャッシュ）は原因ではない（確信度 高）。
- index-status.json {"indexed":0,"excluded":0,"failed":0}、spool/.frame 1件（新規）。
- indexer.py:83-86,104-105 失敗フレームは残り再試行、maintain が 86400秒超を削除。
- 合成 drain 60回: tracemalloc 7MB 一定。keyring 3000回、SQLCipher connect/close 3000回: 増加無視できる。
- maintain: メモリは線形・実行を重ねても増えない。CPU は2次式的（activity.py:24-26 blocks()）。メモリ問題ではないので触らない。
- cli.py:197-205 起動毎に maintain が初回に走る（CPU のみ）。
サブタスク: I3-S1（任意）tests/test_core.py に drain 30回で tracemalloc 差 <5MB の回帰テスト。
