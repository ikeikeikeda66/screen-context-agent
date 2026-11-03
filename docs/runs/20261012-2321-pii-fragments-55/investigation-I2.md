# I2 要約（証拠確認: indexer.py:67, rescan.py:34 がどちらも redact 経由）
indexer/rescan とも pii.redact→scan のみ。B2: indexer.py/rescan.py 変更不要。下流（domains indexer.py:77 redact 後再計算、FTS rescan.py:64-73、outbox/rollup/finish、audit は件数のみ）は既存処理で消える。90日超は ocr_text.split("\n") で行境界一致。冪等: 規則一致時のみ断片を作れば2回目 ({}, {})。
B1: tests/test_rescan.py に FRAGMENT 定数（index 4 完全、9 埋め込み完全、10 ローカル部 "宛先 hanako.test"、窓外）+ fragment_data fixture + テスト3本（indexer一致・FTS、連鎖・冪等、ocr_json NULL）。現 main で失敗確認済み。
B3: 旧版伏せ字済みは purge --keyword TEXT（dry run → --yes）。README 文案あり。
ユーザー決定: 断片の元はメールと電話だけ。旧版データは対象外・purge 案内。最小長と公開ドメインは説明を求められている。
