# 69 get_activity_between: invalid ranges return a generic error with no reason / 不正な範囲の拒否理由がクライアントに返らない open
Found while verifying #68 against a live ActivityWatch instance.

## Problem

`get_activity_between(start, end)` rejects a reversed range (`start >= end`) and a range longer than 7 days, but the client does not learn why. `ValueError` raised in `screen_context/service.py` is not turned into a tool error with its message. The MCP layer wraps it as `UnexpectedToolError`, so the client receives only:

```
Error executing tool get_activity_between
```

The server also writes a full traceback to stderr ("raised an unexpected exception") for what is a normal input validation failure.

## Expected

The client receives the reason, for example `start must be before end` or `the range must be 7 days or shorter`, and the server logs no traceback for invalid input.

## Notes

- The ranges are rejected correctly; only the reported reason is missing.
- Other tools that validate input may behave the same way. Check them when fixing this.

## 日本語

#68 の実環境検証中に見つけました。

### 問題

`get_activity_between(start, end)` は、逆順の範囲（`start >= end`）と 7 日を超える範囲を拒否しますが、クライアントには理由が伝わりません。`screen_context/service.py` で送出した `ValueError` がメッセージ付きのツールエラーに変換されず、MCP 層で `UnexpectedToolError` に包まれます。クライアントに返るのは次の 1 行だけです。

```
Error executing tool get_activity_between
```

また、通常の入力検証エラーなのに、サーバーは標準エラー出力に完全なトレースバック（"raised an unexpected exception"）を出します。

### 期待する動作

クライアントに `start must be before end` や `the range must be 7 days or shorter` などの理由が返り、不正な入力ではサーバーがトレースバックを出さないこと。

### 補足

- 範囲の拒否自体は正しく動いています。理由が返らないことだけが問題です。
- 入力検証を行う他のツールにも同じ挙動がある可能性があります。修正時に確認してください。
# 77 [M8ven] 最新スキャンで残る get_snapshot_image のツール注釈不足を確認・対応する open
## 出典・最新結果
- 公開監査ページ: https://m8ven.ai/mcp/ikeikeikeda66/screen-context-agent?s=readme
- 確認日: 2026-10-12 JST
- 検証日時表示: 2026/10/11 15:53:48（表示のタイムゾーンは未確認）
- 対象コミット: `c3030d2d347bb53816210611d18a1e804f1e021b`
- 評価: B / 89点

## 指摘事項
Quality suggestions は、2ツール中1ツールに注釈があり、`get_snapshot_image` に `readOnlyHint`、`destructiveHint`、`idempotentHint`、`openWorldHint` の4項目が不足していると報告している。

「Tool annotations」と「All four hints declared on every tool」は同じ不足を指しているため、本Issueにまとめる。各項目を実際のハンドラーの挙動に合う boolean として明示する。

外部静的スキャンの結果であり、現行コードと実際の `tools/list` 応答での再現は未確認。実装不備や脆弱性と断定しない。

## 前回との関係
前回の #73 は完了済み。最新ページには `get_current_screen` の注釈不足と `VIKING_API_KEY` の送信先不明の指摘は掲載されていない。これはページ上の表示変化であり、本Issueで個別対応の正しさを検証済みという意味ではない。

## 対応内容
- [ ] 対象コミットと現行版の `get_snapshot_image` 定義・登録経路を確認する。
- [ ] モック環境の `tools/list` 応答で4種類の注釈が存在し、すべて boolean であることを確認する。
- [ ] 不足していれば挙動に合う値を設定する。既に揃っていれば、静的解析で認識されない理由と根拠を記録する。
- [ ] 他の公開ツールも同じ検証に含め、再発を防ぐ。
- [ ] 修正後の再スキャン結果、または誤検知を示す定義・応答・コミットを記録する。

## 完了条件・制約
- 全公開ツールの4種類の注釈が実際の `tools/list` 応答に明示され、挙動に一致する。
- M8venの指摘解消を確認するか、解消しない場合は誤検知・解析上の制約を説明できる根拠を残す。
- コード変更時は `.venv/bin/python -m pytest -q` を実行する。
- テストは実画面を撮影せず、実履歴を読まない。実スクリーンショット、OCR、実キー、個人情報をIssue・リポジトリに含めない。
- MCPの画面データ読み取り専用、capture import禁止、監査ログ非公開の制約を維持する。

