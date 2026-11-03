# I1 要約（証拠確認: pii.py:32 EMAIL、80-91 scan、94-97 redact）
再現: scan(["Name: Taro Example","taro.example@example-test.com","example-test.com","unrelated line"]) → ({0,1}, ['name+email'])、2 が漏れる。
方式: (a) 行が断片を含む + (b) 行トークンが値の一部。メール L=8 で取りこぼし0・誤一致0（L≤7 は "example" "test.com" を誤伏せ、L≥9 は "taro.exam" "example-t" を取りこぼし）。電話 L=7 推奨（DIGIT_RUN でカンマ非区切り）。
A1: pii.py に定数 MIN_EMAIL_FRAGMENT/MIN_PHONE_DIGITS/PUBLIC_MAIL_DOMAINS、email_fragments、phone_numbers、fragment_lines、scan 末尾 `if redact: redact |= fragment_lines(lines, redact)`。完全コードは報告にあり。
A2: tests/test_pii.py テスト骨子あり。
限界: ありふれた長いローカル部（administrator）は他行も伏せる。断片は連鎖しない。カンマ・ピリオド区切りの電話は拾えない。
