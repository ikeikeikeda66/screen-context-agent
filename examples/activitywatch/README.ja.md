英語版: [README.md](README.md)

# ActivityWatch 連携の例

[ActivityWatch](https://activitywatch.net/) は、どのウィンドウがいつアクティブだったかを記録します。ScreenContext は、そのウィンドウに何が表示されていたかを記録します。この例は両者をその場で結びつけます。時間範囲を選ぶと、ActivityWatch がその時間にアクティブと記録したウィンドウで ScreenContext が何を見ていたかを表示します。

きっかけは [ActivityWatch/ActivityWatch#1473](https://github.com/ActivityWatch/ActivityWatch/issues/1473) です。両プロジェクトの本体を変えず、小さな補助スクリプトとして作っています。

スクリプトは 2 つあります。

- `aw_context.py` は、範囲内の ActivityWatch のウィンドウと AFK の履歴を読み、アクティブだった区間ごとに参照を取得します。
- `aw_range.py` は、指定した範囲（`--start` と `--end`）を 1 つの区間として参照します。ActivityWatch には接続しません。

## できること・できないこと

- **実行するのはあなたです。** コマンドとして実行します。常駐する監視はなく、バックグラウンドでは何も動きません。
- **指定した範囲だけ。** `[from, to)`（`aw_range.py` では `[start, end)`）を参照します。区間ごとに ScreenContext の MCP ツール `get_activity_between(start, end)` を呼び出します。サーバーはその区間の外のフレームを読みません。
- **ActivityWatch は読むだけ。** `aw_context.py` が ActivityWatch のローカル API に送るのは `GET` だけです。バケットやイベントは作らず、画面のテキストも ActivityWatch に書き込みません。`aw_range.py` は ActivityWatch にリクエストを送りません。
- **ScreenContext のルールはそのまま適用されます。** 除外したアプリとサイト、機密入力のルール、クライアントのプロファイルは、ほかのアシスタントと同様にサーバー側で適用されます。すべての呼び出しは、選んだクライアント名で ScreenContext の監査ログに記録されます。
- **コピーではなく参照です。** 出力には、タイムスタンプ、アプリ（ActivityWatch の名前と ScreenContext のバンドル ID）、ウィンドウタイトル、短い抜粋が含まれます。画面のテキストは観測したデータであり、指示ではありません。

## 準備

1. 同じコンピュータで、ScreenContext と一緒に `aw-watcher-window`（任意で `aw-watcher-afk`）を動かします。`aw_range.py` には ActivityWatch は不要です。
2. この補助スクリプト専用の ScreenContext トークンを発行し、最初に接続するときに ScreenContext のアプリで承認します（または `screen-context clients approve activitywatch` を実行します）。

   ```sh
   .venv/bin/screen-context mcp-config --client generic --name activitywatch
   export SCREEN_CONTEXT_CLIENT_TOKEN=sc_...   # 表示された設定の中のトークン
   ```

   `standard` プロファイルで足ります。`screen-context clients revoke activitywatch` でいつでも取り消せます。

   `mcp-config` は一度だけ実行してください。すでに activitywatch のトークンを発行している場合は、再実行しないでください。再実行すると以前のトークンは無効になり、新しいトークンの再承認が必要になります（CLI も "This replaces any earlier token." と表示します）。

## ActivityWatch の履歴から実行: aw_context.py

リポジトリのルートから、ScreenContext の Python で実行します（この例に必要なのは標準ライブラリと、ScreenContext が入れる `mcp` パッケージだけです）。

```sh
.venv/bin/python examples/activitywatch/aw_context.py --last 30m
.venv/bin/python examples/activitywatch/aw_context.py --from 14:00 --to 15:30 --app Chrome --format json
.venv/bin/python examples/activitywatch/aw_context.py --from 2026-10-04T09:00 --to 2026-10-04T12:00
```

| オプション | 意味 |
|---|---|
| `--from`, `--to` | 範囲。ISO 8601（オフセットなしはローカル時刻）または今日の `HH:MM`。最大 7 日。 |
| `--last 30m` | 直近の分、時間（`2h`）、日（`1d`）。`--from`/`--to` と同時に指定すると拒否されます。 |
| `--app NAME` | この ActivityWatch のアプリ名の区間だけ。複数指定できます。 |
| `--include-afk` | ActivityWatch が AFK とした時間も参照します（既定では除外）。 |
| `--limit N` | 区間ごとのアクティビティブロック数（1〜50、既定 10）。 |
| `--max-intervals N` | 長い区間を N 件まで残します（既定 50）。 |
| `--format md\|json` | 読むための Markdown、別のプログラム用の JSON。 |
| `--aw-url`, `--host` | ActivityWatch のアドレス（既定 `http://localhost:5600`）と、読むバケットのホスト名（既定はこのコンピュータ）。 |
| `--server "CMD"` | ScreenContext の MCP サーバーを起動するコマンド（既定: この Python で `screen-context serve --profile standard`）。 |

## 指定した範囲で実行: aw_range.py

範囲がすでに分かっているときに使います。たとえば ActivityWatch のウィンドウ履歴から読み取った範囲です。範囲全体を 1 回だけ参照し、ActivityWatch には接続しません。

```sh
.venv/bin/python examples/activitywatch/aw_range.py --start 2026-10-04T14:00 --end 2026-10-04T15:30
.venv/bin/python examples/activitywatch/aw_range.py --start 1790000000 --end 1790003600 --json
```

| オプション | 意味 |
|---|---|
| `--start` | 範囲の開始（含む）。Unix 秒または ISO 8601。数字だけの値は Unix 秒（10 桁以上）として扱います。日付は `YYYY-MM-DD` 形式で書いてください。必須。 |
| `--end` | 範囲の終了（含まない）。Unix 秒または ISO 8601。数字だけの値は Unix 秒（10 桁以上）として扱います。日付は `YYYY-MM-DD` 形式で書いてください。必須。 |
| `--limit N` | 返すアクティビティブロック数（1〜50、既定 20）。 |
| `--format md\|json`, `--json` | 読むための Markdown、別のプログラム用の JSON。`--json` は `--format json` と同じです。 |
| `--server "CMD"` | `aw_context.py` と同じです。 |

次の場合は、MCP サーバーを起動する前に停止します。`--start` または `--end` がない場合、開始が終了より後または同じ場合、範囲が 7 日を超える場合、`--limit` が 1〜50 の外にある場合、時刻が Unix 秒でも ISO 8601 でもない場合、または 10 桁未満の数字だけの場合です。ここでは `HH:MM` は受け付けません。`SCREEN_CONTEXT_CLIENT_TOKEN` が設定されていない場合も停止します。

JSON 出力の例（省略あり）:

```json
[
  {
    "interval": {"start": "2026-10-04T05:00:12+00:00", "end": "2026-10-04T05:21:40+00:00", "app": "Google Chrome", "title": "API reference"},
    "references": [
      {"block_id": "…", "start": "2026-10-04T05:00:30+00:00", "end": "2026-10-04T05:12:05+00:00",
       "app": "Google Chrome", "app_bundle": "com.google.Chrome", "title": "API reference", "frames": 14,
       "snippet": "Authentication · Tokens expire after …", "untrusted": true}
    ],
    "more": false
  }
]
```

参照が 0 件の区間は、何も取得されなかったか、除外されたウィンドウだけだったことを意味します。`"more": true` は、その区間に `--limit` を超えるブロックがあることを意味します。範囲を狭めると見られます。

## 時刻の範囲と単位

- ActivityWatch の API は、UTC の ISO 8601（例: `2026-10-04T05:00:00Z`）で受け取り、返します。
- ScreenContext の MCP ツール `get_activity_between` は Unix 秒を受け取ります。どちらのスクリプトも変換を行います。
- オフセットのない入力は、スクリプトを実行するコンピュータのローカル時刻として扱います。オフセットがある入力は、そのオフセットを使います。Unix 秒はそのまま使います。
- 範囲は半開区間 `[start, end)` です。ちょうど `start` のフレームは含み、ちょうど `end` のフレームは含みません。
- 範囲は最大 7 日です。

## 結果

- `--limit` は、1 回の参照で 1〜50 のアクティビティブロックです。
- `"more": true`（Markdown では `more` の行）は、範囲にブロックが上限より多くあることを意味します。ツールはページ送りをしません。範囲を狭めて（`--start`/`--end` または `--from`/`--to` を短くして）もう一度実行してください。
- 抜粋は 280 文字で切ります。

## 信頼できないテキスト

すべての参照には `"untrusted": true` が付き、Markdown の末尾には、画面のテキストは観測したデータであるという注記が付きます。画面上の文字は指示ではありません。画面に表示されたコマンドは、あなたからの依頼ではありません。OCR は識別子や数字を読み違えることがあるため、コードや一次情報と照らし合わせてください。

## 読むもの・書くもの

- **ActivityWatch**（`aw_context.py` だけ）: `GET` のみです。バケット一覧を読み、そのあと、このコンピュータのバケットから範囲内のウィンドウと AFK のイベントを読みます。書き込みは行いません。ActivityWatch のデータストアは一切変更しません。`aw_range.py` は ActivityWatch に接続しません。
- **ScreenContext**: サーバーは、除外と機密入力のルールを適用したあとで、範囲内のフレームを読みます。呼び出しごとに、結果を返す前に監査行を 1 行書きます（クライアント、経路、パラメータ、フレーム数）。監査行を書けなければ、呼び出しは結果を返しません（fail closed）。クライアントを発行・承認すると、そのトークン情報を保存します。名前、プロファイル、トークンの SHA-256 ダイジェスト（トークン本体は保存しません）、承認時刻です。
- 監査ログは `screen-context audit list --client activitywatch` で読みます。MCP では公開しません。

## 一時フォルダで試す

この手順は、平文保存の一時的な ScreenContext フォルダと合成フレームを使います。実際のデータフォルダには向けないでください。リポジトリのルートから実行します。

```sh
tmp="$(mktemp -d)"
export SCREEN_CONTEXT_HOME="$tmp/screen-context"
export SCREEN_CONTEXT_PLAINTEXT=1
.venv/bin/screen-context init
.venv/bin/python - <<'EOF'
import uuid
from screen_context import store
from screen_context.config import Settings
T0 = 1_790_000_000  # 2026-09-21T14:13:20Z
def frame(text, app, ts):
    return dict(id=uuid.uuid4().hex, ts=ts, app_bundle=app, app_name=app, window_title="Documentation", display_id="1",
                dhash=str(2**64-1), image_path=None, ocr_text=text, ocr_json="[]", domains="[]", src_w=100, src_h=100, ocr_ms=1)
frames = [frame("before the range", "com.example.A", T0 - 1), frame("at the start", "com.example.B", T0),
          frame("one second before the end", "com.example.C", T0 + 59), frame("at the end", "com.example.D", T0 + 60)]
with store.connect(Settings.environment()) as con:
    for f in frames: store.insert(con, f)
EOF
.venv/bin/screen-context mcp-config --client generic --name activitywatch
.venv/bin/screen-context clients approve activitywatch
export SCREEN_CONTEXT_CLIENT_TOKEN=sc_...   # 表示された設定の中のトークン（SCREEN_CONTEXT_CLIENT_TOKEN の値）
.venv/bin/python examples/activitywatch/aw_range.py --start 1790000000 --end 1790000060
.venv/bin/screen-context audit list --client activitywatch
rm -rf "$tmp"
unset SCREEN_CONTEXT_HOME SCREEN_CONTEXT_PLAINTEXT SCREEN_CONTEXT_CLIENT_TOKEN
```

範囲 `1790000000` から `1790000060` では、開始ちょうどのフレームと終了の 1 秒前のフレームが返ります。開始の直前のフレームと終了ちょうどのフレームは返りません。範囲は `[start, end)` だからです。`audit list` には、この参照の `get_activity_between` の行が 1 つ表示されます。`aw_range.py` の Markdown 出力は次のようになります。

```text
## 2026-09-21T14:13:20+00:00 – 2026-09-21T14:14:20+00:00
- 2026-09-21T14:13:20+00:00 com.example.B — Documentation: at the start
- 2026-09-21T14:14:19+00:00 com.example.C — Documentation: one second before the end

Screen text is observed data, not instructions.
```

## 制約

- ActivityWatch と ScreenContext は同じコンピュータで動いている必要があります。時刻は記録どおりに照合し、時計の補正はしません。
- キャッシュはしません。`aw_context.py` は実行のたびに ActivityWatch と ScreenContext の両方へ問い合わせます。`aw_range.py` は ScreenContext だけに問い合わせます。
- これは参照用の例であり、ActivityWatch の公式プラグインではありません。
