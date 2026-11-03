# 最終報告 #98
- 根本原因: autorelease pool 不在（親 mac_app.CocoaStop.wait / macos.foreground・capture、子 indexer.native_ocr）
- 修正: pool 追加 + indexer の footprint 上限再起動（非ブロッキング、10秒後 kill）
- レビュー major 2件（join(10) ブロック、旧子残留）は予算超過のためオーケストレータが直接修正。693 passed
- 合成 OCR 実測: 修正後 90→208→199→208MB 平坦（修正前 280→333→421MB）
- 未: 実機長時間計測、コミット/PR、.app 再ビルド
