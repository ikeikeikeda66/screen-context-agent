# #35 [P3][macOS] First-run setup and bundled CLI / 初回起動セットアップと CLI の同梱 [OPEN]
Roadmap decisions 1 and 12.

## Tasks
- [ ] Bundle the CLI in the app (`Contents/MacOS/screen-context`); `mcp-config` prints that path
- [ ] First run: Screen Recording permission guide → automatic `init` (key and database) → client picker
- [ ] Client picker writes the entry (with a per-client token) into the chosen client's config file after making a backup, or prints it for manual paste
- [ ] i18n strings in both catalogs

## Tests
- [ ] Config writers for each client on temporary files: backup made, existing entries kept, idempotent
- [ ] `verify_bundle.py` checks the bundled CLI

## 日本語

ロードマップの決定1・12。

### タスク
- [ ] CLI をアプリに同梱する（`Contents/MacOS/screen-context`）。`mcp-config` はそのパスを出力する
- [ ] 初回起動：画面収録の許可の案内 → `init`（鍵と DB の作成）を自動実行 → 接続するクライアントの選択
- [ ] 選んだクライアントの設定ファイルに、バックアップを取ってから設定（クライアント別トークン付き）を書き込む。または手動で貼り付けられるよう表示する
- [ ] 表示文言を i18n の両方のカタログに追加する

### テスト
- [ ] 一時ファイルを使い、クライアントごとの設定の書き込みを確認する：バックアップが作られる、既存の設定が残る、何度実行しても同じ結果になる
- [ ] `verify_bundle.py` で同梱した CLI を確認する
---comments---

# #37 [P3][macOS] Uninstall / アンインストール [OPEN]
Roadmap decision 5 (mechanism C).

## Tasks
- [ ] Menu item and CLI `uninstall`: optional `wipe` (key destruction + data folder), remove login item, remove ScreenContext entries from client config files (with backup)
- [ ] Explain what is not removed: exports and backups outside the data folder
- [ ] i18n strings in both catalogs

## Tests
- [ ] Client config cleanup on temporary files keeps other entries

## 日本語

ロードマップの決定5（仕組みC）。

### タスク
- [ ] メニュー項目と CLI の `uninstall`：`wipe`（鍵の破棄＋データフォルダの削除）の選択、ログイン項目の解除、クライアントの設定ファイルから ScreenContext の設定を削除（バックアップを取ってから）
- [ ] 削除されないもの（データフォルダ外の出力ファイルとバックアップ）を説明する
- [ ] 表示文言を i18n の両方のカタログに追加する

### テスト
- [ ] 一時ファイルを使い、クライアントの設定の削除で他の設定が残ることを確認する
---comments---

