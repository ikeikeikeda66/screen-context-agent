# 計画要約（planner）
I1 #8 証拠棚卸し: CLI owner policy 済、バンドルからの Touch ID は #59 に記録がない可能性、Touch ID なし未検証、ネイティブアプリのパスワード欄は Passwords app のみで弱い。go/no-go 下書き（投稿は承認後）。
I2 判定と適用: capture.py に secure_input(adapter)（getattr、例外時 True）、run() は locked の後・capture 前、broker.process_requests は allowed と capture 直前で再判定。macos.Backend.secure_input（ctypes Carbon）。windows.py はコメントで差し込み口。tests/test_secure_input.py。
I3 記録と表示: store.record_skip(settings, category)（例外を投げない）、skip_counts に secure_input、i18n status.secure_input/ui.skip.secure_input、desktop.status_text、ui_views.skipped、review。health state は追加しない。
オーケストレータ採用（推奨案）: 件数は撮影周期ごと1件、判定例外は fail-closed、取り残しは今回は表示のみ、health state 追加なし。
