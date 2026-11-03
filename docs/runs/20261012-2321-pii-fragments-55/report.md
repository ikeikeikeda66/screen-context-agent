# report #55
PR #86（fc2dd91）。607 passed、pii.py を戻すと 28 failed。
レビュー major（一般語の過剰伏せ字）→ 1周で修正。社内ドメインは単独出現のみ（ユーザー決定）。
オーケストレータ修正: test_rescan.py:135 期待値、test_fragment_minimums_are_constants の例を "taro.exa" に。
残: 実機 OCR での確認（#15 手順）。全角 @ を含むアドレスは EMAIL ルール自体が一致しない（既存の制限）。
