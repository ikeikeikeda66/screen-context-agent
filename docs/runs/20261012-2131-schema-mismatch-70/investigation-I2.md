# I2 要約（証拠確認: pyproject.toml:34 entry=cli:main）
実測: DB を開く全コマンド rc=1 Traceback。backup は cli.py:123 が parser.error rc=2。init(v9) Traceback。index は spool を残す。health/status/language/retention/--help/wipe は動く。
**制約違反**: 調査者が `capture --once` を実行し実画面1フレームを一時ディレクトリに spool（削除済み、オーケストレータ検索で残存0件）。以降 capture 実行禁止。
サブタスク: S1 i18n schema.outdated/newer + schema_message + test_i18n / S2 cli main を _main に改名し外側で SchemaMismatch → stderr 1行 exit 1、cli.py:111,123 の前に except SchemaMismatch: raise / S3 tests/test_cli_schema.py / S4 README.md/README.ja.md 新節、CHANGELOG
調停: backup は F1-3 で v3/v9 とも成功するので S3 の backup テストは「成功・manifest schema 実値」に変更。README の「MCP サーバーは起動しません」は決定 (b) と矛盾 → 「起動するがツール呼び出しで案内を返す」に。
