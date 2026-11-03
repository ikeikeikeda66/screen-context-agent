[P1] Truncated duplicate OCR lines escape personal-data redaction / OCR の重複行の断片が伏せ字から漏れる
Found during the real-hardware check of #15 (see the comment there).

Vision OCR sometimes returns a second, truncated reading of a line (another pass or scale). In the test, "Name: …" plus a full e-mail line were redacted correctly, but a separate fragment line such as `example-test.com` (no local part, no `@`) did not match the `EMAIL` pattern on its own and stayed in the stored text. Low severity: a bare domain, not the full address or the name.

## Tasks
- [ ] When a rule redacts a value, also redact other lines in the same frame that contain a sizeable fragment of it (for example the domain or local part of a redacted e-mail, or a digit run of a redacted phone number)
- [ ] Apply the same to `pii-scan` / `rescan` so earlier history is handled the same way
- [ ] Remove the item from "Known limitations" in the README (en/ja) and CHANGELOG

## Tests
- [ ] A frame with a redacted e-mail line and a separate truncated fragment line: both are redacted; unrelated lines stay searchable
- [ ] A fragment shorter than the minimum length is not redacted (no over-redaction of common words)

## 日本語

#15 の実機確認で見つかった問題です。Vision の OCR は、同じ行を途中で切れた形でもう一度返すことがあります。確認では、`Name:` の行と完全なメールアドレスの行は伏せ字になりましたが、別の行として読み取られた断片（例：`example-test.com`。`@` もローカル部もない）は単独では `EMAIL` のパターンに一致せず、そのまま保存されました。漏れたのはドメインだけで、影響は小さいです。

### タスク
- [ ] ルールで伏せ字にした値について、同じ画面の他の行に一定以上の長さの断片（メールアドレスのドメインやローカル部、電話番号の数字の並びなど）があれば、それも伏せ字にする
- [ ] `pii-scan`（過去データへの適用）でも同じ処理をする
- [ ] README（日英）と CHANGELOG の「既知の制限」からこの項目を外す

### テスト
- [ ] 伏せ字にしたメールアドレスの行と、途中で切れた断片の行がある画面：両方とも伏せ字になり、無関係な行は検索できるまま残る
- [ ] 最小の長さに満たない断片は伏せ字にしない（よくある単語を過剰に消さない）
---comments---

