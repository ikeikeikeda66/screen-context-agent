# ScreenContext

[English README](README.md)

ScreenContext は前面ウィンドウを記録し、OS 内蔵の OCR で文字を読み取り、暗号化したローカル履歴に保存します。その履歴を [Model Context Protocol (MCP)](https://modelcontextprotocol.io) で AI アシスタントに提供します。Claude Code、Claude Desktop、Cursor、VS Code、Windsurf、Codex CLI、Gemini CLI など、MCP に対応したクライアントから利用できます。

「さっきブラウザで見ていたエラーメッセージを探して」「今朝読んだ仕様書のページは？」のように依頼して使います。

| プラットフォーム | 状態 |
|---|---|
| macOS 14 以降 | 対応（メニューバーアプリ + CLI）。ソースからビルドして使います。公証済みの配布物はありません。 |
| Windows 10/11 | **ベータ版**（操作ウィンドウ + CLI）。実機での確認は Windows 11 の 1 台です。[Windows（ベータ版）](#windowsベータ版)を参照してください。 |

現在のバージョン: **0.2.0**。変更点: [CHANGELOG.md](CHANGELOG.md)。ライセンス: [MIT](LICENSE)。

## 0.2 で追加したもの

0.2 のテーマは「信頼」です。どのアシスタントに履歴を読ませるか、何を記録しないか、どれだけの期間残すかを、利用者が決められるようにしました。

- **クライアントごとのアクセス管理**：MCP クライアントごとに専用のトークンを発行し、初回にアプリで承認します。クライアントの一覧、各クライアントが読んだ内容を確認でき、いつでも失効させられます。
- **監査ログ**：すべての問い合わせと、返したフレームを暗号化 DB に記録します。読めるのは本人（CLI）だけで、アシスタントからは読めません。
- **機微な入力は保存しない**：カード番号やマイナンバーを含む画面はまるごと破棄します。氏名と住所・電話番号・生年月日・メールアドレスが並んでいる箇所は伏せ字にします。連絡先アプリと決済ページは初期状態で除外します。
- **データの管理**：期間・アプリ・キーワードを指定した削除、保持期間、使用容量の表示、全消去、パスフレーズで保護したバックアップと復元、期間を指定した出力。

0.1 からの更新手順は[0.1 からの更新](#01-からの更新)を参照してください。

## 仕組み

役割を絞った 3 つのプロセスで動きます。

1. **撮影**（macOS はメニューバーアプリ、Windows は操作ウィンドウ）: 前面の 1 ウィンドウだけをネイティブ解像度で取得します。知覚ハッシュで似た画面を省き、暗号化したスプールに書き込みます。
2. **indexer**: OCR（macOS は Apple Vision、Windows は `Windows.Media.Ocr`）を実行し、除外ポリシーと機微入力のルールを適用して、SQLCipher のデータベースとトライグラム FTS5 索引に保存します。
3. **MCP サーバー**（`screen-context serve`）: MCP クライアントが起動します。撮影コードを読み込まず、画面データは読むだけです（書き込むのは監査記録と提案だけです）。クライアントごとのトークンが必要で、すべての結果に「信頼できない観測データ」のラベルを付けます。

詳細は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（英語）を参照してください。今後の計画は [docs/ROADMAP.ja.md](docs/ROADMAP.ja.md) にあります。

## 必要なもの

- Python 3.11 以降と [uv](https://docs.astral.sh/uv/)
- macOS 14 以降、または Windows 10/11（ベータ）
- py2app で macOS の `.app` をビルドする場合は python.org 版か Homebrew 版の Python を使ってください。一部のスタンドアロン版 Python は `zlib` が組み込みのため py2app で失敗します。

## はじめかた（macOS）

**1. インストールと暗号化ストアの作成**

```sh
git clone https://github.com/ikeikeikeda66/screen-context-agent.git
cd screen-context-agent
uv sync --locked --extra macos --extra encrypted --extra dev
.venv/bin/screen-context init
```

`init` は `~/Library/Application Support/ScreenContext` を作成し、ランダムな暗号鍵を macOS のキーチェーンに保存します。鍵を失うと履歴を復号できません。`screen-context backup` でパスフレーズ付きの控えを作れます。

**2. indexer の起動**

```sh
.venv/bin/screen-context index --watch
```

ログイン時に自動で起動する方法は [packaging/macos/README.md](packaging/macos/README.md)（英語）を参照してください。

**3. メニューバーアプリのビルド・署名・起動**

画面収録の権限は署名済みのアプリに付与されるため、撮影はターミナルではなくアプリから行います。毎回同じ署名でビルドすれば、再ビルド後も権限が維持されます。

```sh
sh packaging/macos/signing_identity.sh      # Mac ごとに 1 回だけ：ログインキーチェーンに自己署名の証明書を作成
SCREEN_CONTEXT_SIGN_IDENTITY="ScreenContext Local Signing" sh packaging/build_mac.sh
open dist/ScreenContext.app
```

システム設定 > プライバシーとセキュリティ > 画面収録で ScreenContext を許可し、アプリを開き直してください。再ビルドの後、`codesign` が署名用の鍵を使ってよいか一度だけ確認されることがあります。「常に許可」を選んでください。

- Developer ID の署名でも同じように使えます。`SCREEN_CONTEXT_SIGN_IDENTITY=-`（アドホック署名）でもビルドできますが、再ビルドのたびに権限を付け直す必要があります。
- アプリは公証（notarization）を受けていません。使う Mac の上でビルドしてください。他の Mac からダウンロード・コピーしたアプリは Gatekeeper に止められます。
- ターミナル自身の権限で 1 回だけ試す場合は `.venv/bin/screen-context capture --once` を使います。

**4. アシスタントの接続**：[MCP クライアントの接続](#mcp-クライアントの接続)を参照してください。

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

クライアントが stdio でサーバーを自動起動します。アクセスの流れは次のとおりです。

1. `mcp-config` は実行のたびにそのクライアント用のトークンを発行し、出力する設定に埋め込みます。同じクライアントでもう一度実行するとトークンが入れ替わり、以前の設定は使えなくなります。
2. 新しいトークンが初めて使われたとき、メニューバーアプリ（Windows では操作ウィンドウ）が、そのクライアントに画面履歴の閲覧を許可するかを確認します。アプリを起動しておくか、ターミナルで `screen-context clients approve NAME` を実行して承認します。「許可しない」を選んだトークンは以後使えません。
3. `screen-context clients list` でクライアントの一覧と最後に履歴を読んだ時刻を確認できます。`clients revoke NAME` で次の呼び出しから接続を止められます。`screen-context audit list` で、各クライアントが何を要求し、何を受け取ったかを確認できます。

クライアント別の設定先と HTTP 接続は [docs/MCP-CLIENTS.md](docs/MCP-CLIENTS.md)（英語）を参照してください。

### プロファイルとツール

サーバープロセスごとにプロファイルが 1 つに固定されます。ツールの引数で変更することはできません。また、クライアントのトークンごとに使えるプロファイルの上限が決まっています。

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

## 記録する内容

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
| `pii_combinations` | 初期値は `name+address`、`name+phone`、`name+dob`、`name+email`。OCR の5行以内に両方の情報が現れた場合に適用します（`name+phone:3` のように行数を変えられます）。該当行は `[個人情報]` に置き換え、それ以外の部分は検索できるまま残し、プレビュー画像は保存しません。氏名はラベル（氏名、お名前、フリガナ、`Name:`）と「〇〇 様」の形でのみ判定します。 |

`sensitive_*` と `pii_combinations` のルールは初期状態で有効です。無効にするにはキーを `[]` にします。不正なルールは読み飛ばさず、処理を止めます。これらはリスクベースのルールで、漏えいしたときに直接の被害が大きい入力を対象にしています。個人情報の定義ではありません（法律上は氏名だけでも個人情報に該当しえます）。

- `screen-context pii-check FILE` で、テキストがどのルールに該当するかを確認できます。
- ルールは新しく記録する画面に適用されます。それより前の履歴に適用するには、`screen-context pii-scan`（件数の確認のみ）を実行し、件数を確かめてから `pii-scan --apply` を実行します。該当する画面は、現在の indexer と同じ方法で破棄または伏せ字にし、プレビュー、日次集約、提案の根拠も更新します。取り消しはできません。

## データの管理

| やりたいこと | コマンド | 補足 |
|---|---|---|
| 誤って記録したものを消す | `purge --last 15m`、`--from`/`--to`、`--app`、`--keyword`、`--block`、`--excluded` | 条件は組み合わせられます。`--yes` を付けない場合は削除対象を表示するだけで、どのクライアントに渡したか、どの出力に含めたかもあわせて表示します。`--yes` を付けると、プレビュー、期間内のスプール、日次集約の中の写し、提案の根拠、それを返した監査記録の検索語とフレーム ID もまとめて削除します。解放された DB のページは上書きします。取り消しはできません。 |
| 保存期間を決める | `retention --preview 30 --text 365 --audit 365` | 日数で指定し、`none` で無期限。既定はプレビューと OCR の座標情報が 90 日、テキスト・日次集約・監査ログは期限なし。1時間ごとのメンテナンスで、`purge` と同じ連鎖削除により適用します。 |
| 使用容量を見る | `usage` | プレビュー、DB、スプール、出力ファイルごとの容量。 |
| アシスタントが読んだものを見る | `audit list [--client NAME]`、`audit export` | クライアント、時刻、ツール、検索語、引数、返したフレーム ID。MCP では公開しません。`audit export` は平文の JSON Lines を出力し、出力したこと自体も記録します。 |
| データを取り出す | `export --from T [--to T] --format jsonl\|md\|csv\|viking` | ポリシーを適用します。IDE の画面は `--exclude-ide` を付けない限り含めます。既存のファイルは上書きしません。含めたフレームの ID を監査記録に残すので、後の `purge` で「コピーが外にある」と警告します。管理者は禁止できます（`export_allowed`）。 |
| 別の PC に移す | `backup FILE`、移行先で `restore FILE [--replace]` | DB の一貫したスナップショット、プレビュー、設定を、暗号化したまま 1 つのアーカイブにまとめ、データの鍵をパスフレーズで包んで同梱します（scrypt、AES-GCM）。`restore` は何かを書き込む前にパスフレーズを確認します。パスフレーズがないとアーカイブは開けません。 |
| すべて消す | `wipe`（`ERASE` と入力） | まず資格情報ストアから鍵を削除して暗号化ファイルをすべて読めなくし、そのあとデータフォルダを削除します。実行前にキャプチャと indexer を終了してください。バックアップはパスフレーズがあれば引き続き復元できます。 |

保存の詳細：

- スプールとプレビュー画像は AES-GCM、データベースと全文索引は SQLCipher で暗号化します。鍵は OS の資格情報保管庫（キーチェーン / Windows 資格情報マネージャー）、またはヘッドレス環境では `SCREEN_CONTEXT_KEY` に置きます。
- スプールは 100 枚または 512 MB で受け付けを止めます。24 時間以上処理されない画像は `maintain` で削除します。
- `SCREEN_CONTEXT_PLAINTEXT=1` は開発時のテスト専用です。暗号化が使えないときに自動で平文へ切り替えることはありません。

## 脅威モデル

ScreenContext が防ぐもの：

- **ファイルを持っているが鍵を持っていない人**：盗まれたディスク、コピーされたデータフォルダ、同期されたバックアップ。DB、スプール、プレビューは暗号化されており、`backup` のアーカイブはパスフレーズがないと開けません。
- **許可した範囲を超えて読む MCP クライアント**：クライアントごとに専用のトークンがあり、初回に本人が承認し、プロファイルの範囲に制限され、失効させることもできます。どのクライアントが何を要求し、何を受け取ったかは監査ログで確認できます。
- **残すべきでない記録**：除外ポリシー、カード番号・マイナンバーの検出、個人情報の組み合わせルール、`purge`。

ScreenContext が防がないもの：

- **同じユーザーで動く他のプログラム**：クライアントの設定ファイルからトークンをコピーして `screen-context serve` を起動したり、資格情報ストアから鍵を読んだりできます。そのため、画面収録の許可がなくても履歴を読めます。署名済みアプリの中に鍵を閉じ込める対策は、Developer ID を採用する場合にのみ予定しています（[ロードマップ](docs/ROADMAP.ja.md)）。
- **PC の管理者**：管理設定は事故や規程違反を防ぐためのもので、DRM ではありません。
- **画面に表示された指示**（プロンプトインジェクション）：結果には untrusted の印を付けますが、クライアント側でデータとして扱う必要があります。
- **暗号化ストアの外にあるコピー**：出力したファイルや、すでにクライアントに返した結果には、後からの除外・削除・保持期間は及びません。そうしたコピーがある場合は、`purge` が知らせます。
- **OCR やルールの取りこぼし**：検出はパターンによるものです。OCR が読み誤ったカード番号や、ラベルのない氏名は保存されます。

## 既知の制限

- **macOS での配布**：アプリは公証を受けていないため、使う Mac の上でビルドする必要があります（[はじめかた](#はじめかたmacos)を参照）。
- **パスワード欄**：macOS の Secure Input が有効な間に撮影を止める機能は、まだありません（[#16](https://github.com/ikeikeikeda66/screen-context-agent/issues/16)）。パスワード管理アプリは初期状態で除外しており、パスワード欄の文字は伏せ字で表示されます。
- **個人情報の伏せ字**は OCR に依存します。OCR が同じ行を途中で切れた形でもう一度読み取ることがあり、その断片は伏せ字から漏れることがあります（例：伏せ字にしたメールアドレスのドメイン部分だけ）（[#55](https://github.com/ikeikeikeda66/screen-context-agent/issues/55)）。
- **Windows** はベータ版です。下記を参照してください。

## 0.1 からの更新

DB のスキーマ、MCP の設定、承認の流れが変わりました。既存の履歴は引き継がれます。

1. アプリと indexer を終了し、データフォルダを安全な場所にコピーします。
2. 更新します：`git pull` の後、`uv sync --locked --extra macos --extra encrypted --extra dev`（Windows では `--extra windows`）。
3. `screen-context init` を実行します。DB をスキーマ v3 に移行し、旧形式の `audit.jsonl` を暗号化された監査ログへ移します。移行するまで `health` は `needs_init` を返します。
4. macOS では、アプリを再ビルドします（[はじめかた](#はじめかたmacos)の手順 3）。
5. すべてのクライアントについて `mcp-config` をもう一度実行し、ScreenContext の設定を置き換えます。0.1 の設定ではサーバーが起動しません。各クライアントの初回の呼び出しで承認してください。
6. 任意：`screen-context pii-scan`、続けて `pii-scan --apply` を実行し、0.2 より前に記録した履歴にも新しい機微入力のルールを適用します。

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
# セットアップと常駐プロセス
screen-context init                 データフォルダ・鍵・DB を作成（DB 移行も実行）
screen-context index [--watch]      スプールの画像を OCR して保存
screen-context capture [--once]     ターミナルから撮影（開発用）
screen-context pause | resume       新しい撮影を停止・再開
screen-context status | health      待ち行列と各プロセスの状態
screen-context maintain             保持期間の処理と日次集約
screen-context language [system|en|ja]

# MCP クライアント
screen-context serve [--profile standard|full] [--transport stdio|http] [--port 8765]
screen-context mcp-config [--client NAME] [--profile standard|full] [--name TOKEN_NAME]
screen-context clients list | approve NAME | revoke NAME
screen-context audit list|export [--client NAME] [--since YYYY-MM-DD] [--limit N]

# データの管理
screen-context purge [--from T] [--to T] [--last 15m] [--app ID] [--keyword TEXT] [--block ID] [--excluded] [--yes]
screen-context retention [--preview D] [--text D] [--audit D]   保持日数（none で無期限）
screen-context usage                    データ種別ごとの使用容量
screen-context pii-check FILE           テキストがどの機微入力ルールに該当するか
screen-context pii-scan [--apply]       過去の記録にルールを適用する
screen-context export --from T [--to T] [--format jsonl|md|csv|viking] [--out DIR] [--exclude-ide]
screen-context backup FILE | restore FILE [--replace]   パスフレーズで保護したアーカイブ
screen-context wipe                     鍵を削除してから全データを削除（取り消し不可）

# 任意機能
screen-context diary-material DATE [--budget 6000] [--lang en|ja]
screen-context proposal prepare|simulate|finish
screen-context push DATE                1日分をローカルの OpenViking サーバーへ送る
```

`export DATE`（OpenViking 向けの1日分）は 0.2 では引き続き使えますが、非推奨です。`--format viking` を使ってください。

### 任意機能: 日記の素材と定期提案

- `diary-material DATE` は 1 日分の画面履歴を、文字数上限つきの Markdown にまとめて出力します。日記や日報のプロンプトの入力に使います。
- `proposal prepare` はスケジューラー（cron やエージェントフレームワーク）の事前スクリプトとして使う想定です。新しい観測があるときだけ素材を出力し、ないときは最終行に `{"wakeAgent": false, ...}` を出力するので、エージェントの起動を省略できます。エージェントは `submit_proposal` で提案を登録します。根拠はアシスタント以外の画面からの引用である必要があり、同じ結論は 24 時間抑制されます。`proposal finish --run-id ID --response-file FILE` で実行を閉じます。

### 任意機能: OpenViking

`push DATE` は1日分の日次集約を出力し、それをローカルの [OpenViking](https://github.com/volcengine/OpenViking) サーバー（`http://127.0.0.1:1933`、必要なら `VIKING_API_KEY`）へ送ります。自動では送信しません。出力済みのデータは、後から除外を追加しても取り消されません。

## Windows（ベータ版）

Windows 版には操作ウィンドウ（開始・一時停止・停止・言語・MCP クライアント設定の表示）と同じ CLI があります。自動テストに合格しており、Windows 11 23H2 の実機 1 台（単一モニター、96 DPI）で、撮影と OCR、クライアントの承認、スキーマの移行、Edge での決済ページの除外、資格情報マネージャーを使った backup・wipe・restore を確認しました。

まだ確認していないもの：他の DPI 設定と複数モニター、Chrome のパスワード欄、撮影中の UAC 表示、連絡先アプリの既定の除外（[#25](https://github.com/ikeikeikeda66/screen-context-agent/issues/25)）。撮影ライブラリのクラッシュを避けるため、画面ロック中は撮影しません（[#47](https://github.com/ikeikeikeda66/screen-context-agent/issues/47)）。問題があれば、Windows のバージョンと画面構成を添えて Issues で報告してください。

セットアップ、配布用ビルド、受け入れ確認の手順は [docs/WINDOWS.md](docs/WINDOWS.md)（英語）を参照してください。

## 開発

```sh
uv sync --locked --extra macos --extra encrypted --extra dev   # Windows では --extra windows
.venv/bin/python -m pytest -q
.venv/bin/python packaging/verify_bundle.py                    # macOS アプリのビルド後
```

コントリビューションを歓迎します。[CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。セキュリティ上の問題は [SECURITY.md](SECURITY.md) の方法で報告してください。
