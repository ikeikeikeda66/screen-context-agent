# I2 調査報告（要約保存）
結論（確信度 高）: indexer.py:21-31 native_ocr が autorelease pool なしで CGImage/CGBitmapContext/VN* を大量生成（recognize 1回 + recognize_tiled 9タイル、各 _scale で2倍 bitmap）。cli.py:196-201 の watch ループに pool も run loop もない。
実測（合成画像 2560x1440、scratchpad/exp.py）: pool なし 90→280→333→421MB（0/20/40/60回）、約5.5MB/回。pool あり 98→207→206→194MB で平坦、しかも速い（192s vs 241s）。
grep autoreleasepool/autorelease_pool in screen_context: 該当なし。
サブタスク:
- I2-S1 native_ocr darwin 分岐を `with objc.autorelease_pool():` で包む。src/cg が None なら RuntimeError("Image: failed to import")。
- I2-S2 tests/test_ocr_memory.py 新規。偽 objc/Quartz/Foundation/vision を sys.modules に差し込み、pool enter/exit 1回、recognize が pool 内、cg None で RuntimeError かつ pool exit を検証。
- I2-S3 vision.py は変更不要（S1 後の実測次第）。
