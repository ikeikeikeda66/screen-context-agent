# 調査計画要約（planner）
pii.py: signals → scan(lines, rules) が組み合わせ+window で行集合、redact が行全体を placeholder・bbox None。値は保持しない。断片行は信号に一致せず漏れる。
indexer drain と rescan はどちらも pii.redact を呼ぶ → scan 側に断片照合を入れれば両方と pii-check に効く。
I1 pii.py 断片ルール（A1 実装、A2 tests/test_pii.py）
I2 indexer/rescan 一致・連鎖・冪等（B1 tests/test_rescan.py、B2 コード変更不要確認、B3 旧版伏せ字済みフレーム）
I3 README/CHANGELOG（C1-C3）
設計論点 Q1 最小長 メール8/電話7、Q2 メール・電話のみ、Q3 公開メールドメイン除外、Q4 旧版伏せ字済みは対象外+purge 案内、Q5 0.2.0 は残し Unreleased に追加

## ユーザー決定（2026-10-12）
断片の元はメールと電話のみ / 最小長 メール8・電話7 / 公開メールドメインは断片にしない（ローカル部は断片） / 旧版伏せ字済みは対象外、README で purge --keyword を案内 / CHANGELOG 0.2.0 は残し Unreleased に追加（Q5 は推奨を採用、未質問）
- 社内ドメイン: ドメイン断片は単独で現れる行だけ（他人のアドレス・URL 内は対象外）（2026-10-12 ユーザー決定）
## レビュー（final-reviewer）
major: トークン側比較で一般語（customer/software/姓）を伏せる。minor: 単語境界なし・役割ローカル部、O(g^3)、元行 NFKC 未適用、README 既知の制限を削除しすぎ、社内ドメイン未記載、Invoice 偶然一致、CHANGELOG 日本語に purge 案内なし。→ 1周で修正。
