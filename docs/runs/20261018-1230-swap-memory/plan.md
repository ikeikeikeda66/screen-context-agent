# 調査計画（investigation-planner 出力、要約保存）

事前観測: ~/Library/Logs/ScreenContext/indexer.log に Traceback 94件（末尾 `RuntimeError: Database schema version 4 does not match 3`、`Image: failed to import` 連続）。~/Library/Logs/DiagnosticReports/Python-2026-10-17-15{4918,5950}.ips, Python-2026-10-17-1606{22,25,31}.ips。traceback パスが開発 checkout と ~/.local/share/uv/python/cpython-3.12.13 → 子が .app 同梱 Python でなく checkout を実行している可能性。
rss-samples.txt 列: 時刻 子RSS(KB) 子etime 親RSS(KB)。子PID 33622(index --watch), 親PID 33614。

## I1 親アプリ（GUI とキャプチャ）
範囲: mac_app.py main()/CocoaStop.wait（nextEventMatchingMask 手動ループ）、capture.py run/spool/dhash、platforms/macos.py foreground()（毎秒 NSRunLoop.runUntilDate_, CGWindowListCopyWindowInfo）/capture()（SCShareableContent, SCContentFilter, NSMutableData, CGImageDestination）、platforms/sck.py _sync/shareable_content、ループ内 broker.process_client_requests/process_requests, reauth.process_requests, sessions.Presence.tick。
仮説: (1) メインスレッド手動ループで autorelease pool が空にならず ObjC オブジェクト蓄積。(2) 画像コピー重複・縮小なし。(3) broker/reauth/sessions がモジュールレベルで溜める。
確認: 合成ループ（画面キャプチャしない）で objc.autorelease_pool() 有無の RSS 差、vmmap --summary / heap を親PIDに2回。
完了: 親RSS増加率(MB/h)、主因が ObjC か Python ヒープか、修正方針を合成ループで確認。
触るファイル見込み: capture.py, mac_app.py, platforms/macos.py, platforms/sck.py, tests/test_capture.py, tests/test_macos_capture.py, tests/test_macos_foreground.py

## I2 index --watch 子プロセスの OCR（ObjC/Vision）
範囲: indexer.py native_ocr（NSData→CGImageSource→CGImage、vision.recognize 1回 + recognize_tiled 9回）、platforms/vision.py recognize/recognize_tiled/_scale（2倍 CGBitmapContext）、indexer.log の `Image: failed to import` の出所、子PID の RSS。
仮説: (1) CLI に run loop も autorelease pool もなく VN*/CGImage/bitmap context が解放されない。(2) Vision/ANE モデル資源が毎回確保。(3) `Image: failed to import` 毎に資源残留。
確認: PIL 合成画像に native_ocr 200回、pool 有無で RSS 比較。heap 子PID の VN*/CGImage 数。
完了: OCR回数比例かを合成画像で確定、pool/再利用で止まることを数値で。
触るファイル見込み: indexer.py（native_ocr のみ）, platforms/vision.py, tests/test_ocr_memory.py（新規、ObjC モックで pool 境界のみ検証）

## I3 indexer の Python 側処理
範囲: cli.py 190〜210行（5秒ごと drain、3600秒ごと maintain）、indexer.py drain/maintain、service.py get_daily_rollup、purge.py、データフォルダの index-status.json と spool/ の件数（中身は読まない）。
仮説: (1) 失敗フレームが spool に残り5秒ごとに再OCR。(2) maintain が毎時全期間 rollup、ピーク増。(3) DB接続やキャッシュ蓄積。
確認: index-status.json の failed/last_error_type、spool ファイル数・mtime。合成DBで maintain 前後 ru_maxrss。tracemalloc で drain 1000回。
完了: 各要因の有無を数値根拠で判定。
触るファイル見込み: cli.py, service.py, purge.py, tests/test_retention.py, tests/test_core.py（indexer.py drain/maintain は I2 の後）

## I4 プロセスの寿命・再起動・メモリ上限
範囲: desktop.py Workers（spawn Event→resource_tracker、600秒3回再起動上限）/CommandProcess、launch.py indexer_workers/start_indexer/stop_indexer、quick.py cli_command/child_env、locking.py、indexer.log Traceback 時刻分布、.ips、ps。
仮説: (1) 親異常終了で子が取り残され重複保持。(2) 起動直後失敗で再起動ループ。(3) RSS 上限による保護がない。
完了: 取り残し/重複の判定、RSS 上限保護の設計案（閾値、計測方法、i18n 文言）。
触るファイル見込み: desktop.py, launch.py, quick.py, i18n.py（両カタログ）, tests/test_desktop.py, tests/test_launch.py

## 順序
調査は並列。修正は I2 の native_ocr 先、I3 の indexer.py 変更は後。I4 の上限は保険で、根本対処後に閾値決定。issue は調査後・修正前。

## 人間に確認が要る点（調査で代替可能なものは先に進む）
1 48GB の内訳（どのプロセスか） 2 .app のビルドと子が checkout Python で動く構成の意図 3 10-17 15:49〜16:06 クラッシュ時の操作 4 キャプチャ間隔・ディスプレイ構成 5 修正後の実機長時間計測、heap/vmmap/leaks の実行可否
