# ScreenContext

[English README](README.md)

ScreenContext は前面ウィンドウを記録し、OS 内蔵の OCR で文字を読み取り、暗号化したローカル履歴に保存します。その履歴を [Model Context Protocol (MCP)](https://modelcontextprotocol.io) で AI アシスタントに提供します。Claude Code、Claude Desktop、Cursor、VS Code、Windsurf、Codex CLI、Gemini CLI など、MCP に対応したクライアントから利用できます。

「さっきブラウザで見ていたエラーメッセージを探して」「今朝読んだ仕様書のページは？」のように依頼して使います。

| プラットフォーム | 状態 |
|---|---|
| macOS 14 以降 | 対応（メニューバーアプリ + CLI） |
| Windows 10/11 | **ベータ版**（操作ウィンドウ + CLI）。多様な実機環境での検証はまだ限られています。 |

ライセンス: [MIT](LICENSE)

## 仕組み

役割を絞った 3 つのプロセスで動きます。

1. **撮影**（macOS はメニューバーアプリ、Windows は操作ウィンドウ）: 前面の 1 ウィンドウだけをネイティブ解像度で取得します。知覚ハッシュで似た画面を省き、暗号化したスプールに書き込みます。
2. **indexer**: OCR（macOS は Apple Vision、Windows は `Windows.Media.Ocr`）を実行し、除外ポリシーを適用して、SQLCipher のデータベースとトライグラム FTS5 索引に保存します。
3. **MCP サーバー**（`screen-context serve`）: MCP クライアントが起動します。撮影コードを読み込まず、画面データは読むだけです（書き込むのは監査記録と提案だけです）。クライアントごとのトークンが必要で、すべての結果に「信頼できない観測データ」のラベルを付けます。

詳細は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（英語）を参照してください。今後の計画は [docs/ROADMAP.ja.md](docs/ROADMAP.ja.md)にあります。

## 必要なもの

- Python 3.11 以降と [uv](https://docs.astral.sh/uv/)
- macOS 14 以降、または Windows 10/11（ベータ）
- py2app で macOS の `.app` をビルドする場合は python.org 版か Homebrew 版の Python を使ってください。一部のスタンドアロン版 Python は `zlib` が組み込みのため py2app で失敗します。

## はじめかた（macOS）

```sh
git clone https://github.com/ikeikeikeda66/screen-context-agent.git
cd screen-context-agent
uv sync --locked --extra macos --extra encrypted --extra dev
.venv/bin/screen-context init
```

`init` は `~/Library/Application Support/ScreenContext` を作成し、ランダムな暗号鍵を macOS のキーチェーンに保存します。鍵を失うと履歴を復号できません。

ターミナルで indexer を起動します。

```sh
.venv/bin/screen-context index --watch
```

メニューバーアプリをビルドして起動します。画面収録の権限は .app に付与されるため、撮影はターミナルではなくアプリから行います。

```sh
# "-" はローカル用のアドホック署名です。再ビルド後も画面収録の権限を
# 維持するには Developer ID の署名を指定してください。
SCREEN_CONTEXT_SIGN_IDENTITY=- sh packaging/build_mac.sh
open dist/ScreenContext.app
```

システム設定 > プライバシーとセキュリティ > 画面収録で ScreenContext を許可し、アプリを開き直してください。ログイン時に indexer を起動する方法は [packaging/macos/README.md](packaging/macos/README.md)（英語）を参照してください。

ターミナル自身の権限で 1 回だけ試す場合は `.venv/bin/screen-context capture --once` を使います。

### メニューバー

![ScreenContext のメニューバー: 撮影間隔と言語のサブメニュー](docs/images/menu-bar-ja.png)

記録中は **SC 撮影**、一時停止中は **SC 停止** と表示されます（英語設定では **SC Rec** / **SC Paused**）。

- **撮影を一時停止 / 撮影を再開**: 動画を見るときや、見せたくない内容を表示するときに使います。状態は保存されます。
- **撮影間隔**: 5秒、15秒（既定）、30秒、1分、2分、5分。再起動せずに反映されます。画面に変化がなければ保存しません。
- **言語**: システムの設定に従う / English / 日本語。メニュー、ダイアログ、生成する素材の文言がすべてこの設定に従います。

## MCP クライアントの接続

使っているクライアント用の設定を出力します。

```sh
.venv/bin/screen-context mcp-config --client claude-code     # `claude mcp add` コマンドを出力
.venv/bin/screen-context mcp-config --client claude-desktop
.venv/bin/screen-context mcp-config --client cursor
.venv/bin/screen-context mcp-config --client vscode
.venv/bin/screen-context mcp-config --client windsurf
.venv/bin/screen-context mcp-config --client codex           # ~/.codex/config.toml 用の TOML
.venv/bin/screen-context mcp-config --client gemini
.venv/bin/screen-context mcp-config --client generic         # 汎用の mcpServers JSON
```

クライアントが stdio でサーバーを自動起動します。先に `init` を実行してください。`mcp-config` は実行のたびにそのクライアント用のトークンを発行し、出力する設定に埋め込みます。同じクライアントでもう一度実行するとトークンが入れ替わり、以前の設定は使えなくなります。新しいトークンが初めて使われたとき、メニューバーアプリ（Windows では制御ウィンドウ）が、そのクライアントに画面履歴の閲覧を許可するかを確認します。アプリを起動しておくか、`screen-context clients approve NAME` で承認してください。`screen-context clients list` でクライアントの一覧と最後に履歴を読んだ時刻を、`clients revoke NAME` で次の呼び出しから接続を止められます。クライアント別の設定先と HTTP 接続は [docs/MCP-CLIENTS.md](docs/MCP-CLIENTS.md)（英語）を参照してください。

### プロファイルとツール

サーバープロセスごとにプロファイルが 1 つに固定されます。ツールの引数で変更することはできません。

| ツール | `standard`（既定） | `full` |
|---|---|---|
| `search_screen_history` | ○ | ○ |
| `get_recent_activity` | ○ | ○ |
| `get_context_around` | ○ | ○ |
| `get_day_material`（日報・日記の根拠） | ○ | ○ |
| `get_activity_timeline` | | ○ |
| `get_daily_rollup` | | ○ |
| `get_diary_material` | | ○ |
| `get_capture_health` | | ○ |
| `get_activity_delta`（署名付き cursor、固定スナップショット） | | ○ |
| `submit_proposal`（提案 outbox へ書き込み） | | ○ |
| `get_snapshot_image` | | ○ |
| `get_current_screen`（呼び出しごとにローカルで承認） | | ○ |

- `standard` はコーディングアシスタント向けです。IDE とターミナルの画面（ポリシーの `ide_apps`）を返しません。アシスタントはソースコードを直接読めるためです。
- `full` は、スクリーンショットやタイムラインを渡してよい個人用エージェント向けです。
- 旧バージョンの `claude_code` と `openclaw` は、それぞれ `standard` と `full` の別名として引き続き使えます。

すべての応答とレコードに `source=observed_screen`、`trust=untrusted` を付けます。これはラベルであり、プロンプトインジェクションを防ぐものではありません。画面の文字は命令ではなくデータとして扱ってください。

## プライバシーと保存

データフォルダの `policy.json` を編集します。撮影時とすべての問い合わせ時に読み直すため、追加した除外は過去の記録の検索・活動要約・画像取得にも適用されます。不正な設定は処理を失敗させ、除外を無効にはしません。

| キー | 意味 |
|---|---|
| `denied_apps` | 撮影しないバンドル ID（macOS）またはプロセス名（Windows）。既定でパスワード管理アプリとビデオ会議アプリを含みます。 |
| `denied_domains` | OCR した文字にこれらのドメインが含まれる画面を破棄します。URL が表示され、正しく読み取れた場合に限り有効です。 |
| `denied_title_patterns` | ウィンドウタイトルに適用する正規表現。 |
| `ide_apps` | `standard` プロファイルで返さないアプリ。 |
| `ai_output_apps`, `ai_output_title_patterns` | アシスタント自身の出力を表示している画面。提案の根拠には使えません。 |
| `sensitive_detectors` | 初期値は `card_number`（13〜19桁、発行者の先頭番号、Luhn チェック）と `my_number`（チェックデジットが正しい12桁で、近くに「個人番号」「マイナンバー」の表記があるもの）。該当した画面は、保存前にテキストと画像をまとめて破棄し、理由の件数だけを記録します。 |
| `sensitive_apps`, `sensitive_title_patterns`, `sensitive_url_patterns` | 連絡先アプリと、決済・支払いページ（タイトル、または表示中の URL の `/checkout`・`/payment`・`/billing` のパス）を初期状態で除外します。 |

| `pii_combinations` | 初期値は `name+address`、`name+phone`、`name+dob`、`name+email`。OCR の5行以内に両方の情報が現れた場合に適用します（`name+phone:3` のように行数を変えられます）。該当行は `[個人情報]` に置き換え、それ以外の部分は検索できるまま残し、プレビュー画像は保存しません。氏名はラベル（氏名、お名前、フリガナ、`Name:`）と「〇〇 様」の形でのみ判定します。`screen-context pii-check FILE` でテキストに対する判定を確認できます。 |

`sensitive_*` と `pii_combinations` のルールは初期状態で有効です。無効にするにはキーを `[]` にします。不正なルールは読み飛ばさず、処理を止めます。これらはリスクベースのルールで、漏えいしたときに直接の被害が大きい入力を対象にしています。個人情報の定義ではありません（法律上は氏名だけでも個人情報に該当しえます）。ルールは新しく記録する画面に適用されます。それより前の記録に適用するには、`screen-context pii-scan`（件数の確認のみ）を実行し、続けて `pii-scan --apply` を実行します。該当する画面は、現在の indexer と同じ方法で破棄または伏せ字にします。伏せ字にした画面のプレビューは削除し、日次集約と提案の根拠も更新します。取り消しはできません。

- スプールとプレビュー画像は AES-GCM、データベースと全文索引は SQLCipher で暗号化します。鍵は OS の資格情報保管庫（キーチェーン / Windows 資格情報マネージャー）、またはヘッドレス環境では `SCREEN_CONTEXT_KEY` に置きます。
- スプールは 100 枚または 512 MB で受け付けを止めます。24 時間以上処理されない画像は `maintain` で削除します。
- 保持期間：プレビュー画像と OCR の座標情報は 90 日で削除します。検索用の OCR テキスト、日次集約、監査ログは、期限を設定しない限り保持します。`screen-context retention --preview 30 --text 365 --audit 365` で日数を設定し（`none` は無期限）、1時間ごとのメンテナンスで適用します。期限切れのテキストは `purge` と同じ連鎖削除で消します。`screen-context usage` で、プレビュー、データベース、スプール、出力ファイルが使っている容量を確認できます。
- `screen-context purge` は記録を完全に削除します。対象は、期間（`--from`/`--to` または `--last 15m`）、`--app`、`--keyword`、`--block`（1つの活動ブロック）、`--excluded`（現在のポリシーで既に隠れているもの）で指定し、組み合わせることもできます。`--yes` を付けない場合は削除対象を表示するだけです。その際、どのクライアントに渡したか、どの出力に含めたかもあわせて表示します。`--yes` を付けると、プレビュー画像、期間内の未処理のスプール、日次集約の中の写し、そのフレームを引用した提案の根拠、それを返した監査記録の検索語とフレーム ID もまとめて削除します。解放された DB のページは上書きします。取り消しはできません。すでに PC の外に出たデータは取り戻せません。
- 監査ログは暗号化 DB 内のテーブルです。ツールの呼び出しごとに、クライアント、時刻、ツール、検索語、その他の引数、返却したフレームの ID を記録するので、どのクライアントが何を読んだかを確認できます。MCP では公開しません。`screen-context audit list` または `audit export`（平文の JSON Lines。出力したこと自体も記録されます）で確認します。`init` は旧形式の `audit.jsonl` を取り込んでから削除します。
- `screen-context backup FILE` は1つのアーカイブを作ります。中身は DB の一貫したスナップショット、プレビュー画像、設定で、いずれも暗号化されたままです。データの鍵は、パスフレーズから導出した鍵（scrypt、AES-GCM）で包んで同梱します。`screen-context restore FILE` は、何かを書き込む前にパスフレーズを確認します。既存の履歴は `--replace` を付けない限り上書きせず、鍵は資格情報ストアに登録します。別の PC への移行に使えます。パスフレーズを失うとアーカイブは開けません。
- `screen-context wipe`（`ERASE` と入力）は、まず資格情報ストアから鍵を削除して暗号化されたファイルをすべて読めなくし、そのあとデータフォルダを削除します。実行前にキャプチャと indexer を終了してください。バックアップはパスフレーズがあれば引き続き復元できます。
- `SCREEN_CONTEXT_PLAINTEXT=1` は開発時のテスト専用です。暗号化が使えないときに自動で平文へ切り替えることはありません。

## 脅威モデル

ScreenContext が防ぐもの：

- **ファイルを持っているが鍵を持っていない人**：盗まれたディスク、コピーされたデータフォルダ、同期されたバックアップ。DB、スプール、プレビューは暗号化されており、`backup` のアーカイブはパスフレーズがないと開けません。
- **許可した範囲を超えて読む MCP クライアント**：クライアントごとに専用のトークンがあり、初回に本人が承認し、プロファイルの範囲に制限され、失効させることもできます。どのクライアントが何を要求し、何を受け取ったかは監査ログで確認できます（`screen-context audit list`）。
- **残すべきでない記録**：除外ポリシー、カード番号・マイナンバーの検出、個人情報の組み合わせルール、`purge`。

ScreenContext が防がないもの：

- **同じユーザーで動く他のプログラム**：クライアントの設定ファイルからトークンをコピーして `screen-context serve` を起動したり、資格情報ストアから鍵を読んだりできます。そのため、画面収録の許可がなくても履歴を読めます。署名済みアプリの中に鍵を閉じ込める対策は、Developer ID を採用する場合にのみ予定しています（[ロードマップ](docs/ROADMAP.ja.md)）。
- **PC の管理者**：管理設定は事故や規程違反を防ぐためのもので、DRM ではありません。
- **画面に表示された指示**（プロンプトインジェクション）：結果には untrusted の印を付けますが、クライアント側でデータとして扱う必要があります。
- **暗号化ストアの外にあるコピー**：出力したファイルや、すでにクライアントに返した結果には、後からの除外・削除・保持期間は及びません。そうしたコピーがある場合は、`purge` が知らせます。
- **OCR やルールの取りこぼし**：検出はパターンによるものです。OCR が読み誤ったカード番号や、ラベルのない氏名は保存されます。

## 設定

| 環境変数 | 用途 |
|---|---|
| `SCREEN_CONTEXT_HOME` | データフォルダ。既定は `~/Library/Application Support/ScreenContext`（macOS）、`%USERPROFILE%\.screen-context`（Windows）。 |
| `SCREEN_CONTEXT_KEY` | 64 桁の 16 進数。OS の資格情報保管庫の代わりに使います（ヘッドレス環境）。 |
| `SCREEN_CONTEXT_LANG` | `en` または `ja`。保存した言語設定より優先します。 |
| `SCREEN_CONTEXT_OCR_LANGUAGES` | OCR 言語をカンマ区切りで指定（例: `en-US,ja-JP`）。macOS の既定は `ja-JP,en-US`、Windows の既定はユーザーの表示言語です（Windows OCR は先頭の 1 言語のみ使用）。 |
| `SCREEN_CONTEXT_CLIENT_TOKEN` | `mcp-config` が設定するクライアントのトークン。有効なトークンがないとサーバーは起動しません。 |

言語は `screen-context language en|ja|system` でも設定できます。

## CLI

```text
screen-context init                 データフォルダ・鍵・DB を作成（DB 移行も実行）
screen-context index [--watch]      スプールの画像を OCR して保存
screen-context capture [--once]     ターミナルから撮影（開発用）
screen-context pause | resume       新しい撮影を停止・再開
screen-context status | health      待ち行列と各プロセスの状態
screen-context maintain             保持期間の処理と日次集約
screen-context serve [--profile standard|full] [--transport stdio|http] [--port 8765]
screen-context mcp-config [--client NAME] [--profile standard|full] [--name TOKEN_NAME]
screen-context clients list | approve NAME | revoke NAME
screen-context language [system|en|ja]
screen-context diary-material DATE [--budget 6000] [--lang en|ja]
screen-context proposal prepare|simulate|finish
screen-context backup FILE | restore FILE [--replace]   パスフレーズで保護したアーカイブ
screen-context wipe                     鍵を削除してから全データを削除（取り消し不可）
screen-context usage                    データ種別ごとの使用容量
screen-context retention [--preview D] [--text D] [--audit D]   保持日数（none で無期限）
screen-context purge [--from T] [--to T] [--last 15m] [--app ID] [--keyword TEXT] [--block ID] [--excluded] [--yes]
screen-context pii-check FILE           テキストがどの機微入力ルールに該当するか
screen-context pii-scan [--apply]       過去の記録にルールを適用する
screen-context audit list|export [--client NAME] [--since YYYY-MM-DD] [--limit N]
screen-context export --from T [--to T] [--format jsonl|md|csv|viking] [--out DIR] [--exclude-ide]
screen-context push DATE                1日分をローカルの OpenViking サーバーへ送る
```

### 任意機能: 日記の素材と定期提案

- `diary-material DATE` は 1 日分の画面履歴を、文字数上限つきの Markdown にまとめて出力します。日記や日報のプロンプトの入力に使います。
- `proposal prepare` はスケジューラー（cron やエージェントフレームワーク）の事前スクリプトとして使う想定です。新しい観測があるときだけ素材を出力し、ないときは最終行に `{"wakeAgent": false, ...}` を出力するので、エージェントの起動を省略できます。エージェントは `submit_proposal` で提案を登録します。根拠はアシスタント以外の画面からの引用である必要があり、同じ結論は 24 時間抑制されます。`proposal finish --run-id ID --response-file FILE` で実行を閉じます。

### 出力

`export --from 2026-09-01 --to 2026-10-01 --format md` は、期間内のフレームを1つの平文ファイルとして `exports/`（または `--out` で指定した場所）に出力します。形式は `jsonl`、`md`、`csv` のいずれかです。`viking` を指定すると、1日ごとの日次集約 JSON を出力します。現在のポリシーを適用します。IDE とターミナルの画面は、`--exclude-ide` を付けない限り含めます。既存のファイルは上書きしません。出力のたびに、含めたフレームの ID を監査記録に残すので、後でそのフレームを `purge` するときに「コピーが外にある」と警告が出ます。管理者は出力を禁止できます（`export_allowed`）。`export DATE` は1リリースの間だけ使えますが、非推奨です。

### 任意機能: OpenViking

`push DATE` は1日分の日次集約を出力し、それをローカルの [OpenViking](https://github.com/volcengine/OpenViking) サーバー（`http://127.0.0.1:1933`、必要なら `VIKING_API_KEY`）へ送ります。自動では送信しません。出力済みのデータは、後から除外を追加しても取り消されません。

## Windows（ベータ版）

Windows 版には操作ウィンドウ（開始・一時停止・停止・言語・MCP クライアント設定の表示）と同じ CLI があります。**ベータ版**です。Windows API を模擬した自動テストには合格していますが、実機での確認（DPI、複数モニター、ロックと復帰、資格情報）はまだ限られています。問題があれば Issues で報告してください。

セットアップ、配布用ビルド、受け入れ確認の手順は [docs/WINDOWS.md](docs/WINDOWS.md)（英語）を参照してください。

## 開発

```sh
uv sync --locked --extra macos --extra encrypted --extra dev   # Windows では --extra windows
.venv/bin/python -m pytest -q
.venv/bin/python packaging/verify_bundle.py                    # macOS アプリのビルド後
```

コントリビューションを歓迎します。[CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。セキュリティ上の問題は [SECURITY.md](SECURITY.md) の方法で報告してください。
