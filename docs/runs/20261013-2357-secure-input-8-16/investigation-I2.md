# I2 要約（証拠確認: capture.py:81-86、broker.py:101-108）
撮影経路は capture.run（capture.py:86）と broker.process_requests（broker.py:108）のみ。locked と同位置に secure_input(adapter)。IsSecureEventInputEnabled 実測 bool、0.105µs。Presence 変更不要（presence.state に CHECK 制約、意味が違う）。
I2-a macos load_secure_input + Backend.secure_input（読み込み失敗は呼び出し時に例外→fail-closed）/ I2-b capture.secure_input + run 挿入 / I2-c broker allowed と capture 直前 / I2-d windows コメント / I2-e tests/test_secure_input.py 骨子
オーケストレータ決定: issue #16「capture status に記録」に従い capture-status.json に {"ts","status":"secure_input"} を書く（I2 は書かない推奨だった）。
