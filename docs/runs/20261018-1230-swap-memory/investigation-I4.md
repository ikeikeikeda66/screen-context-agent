# I4 調査報告（要約保存）
結論: 取り残し・重複・再起動ループは未確認（現行 .app 子は同梱 Python 3.13、indexer.lock の flock で重複不可）。indexer.log の Traceback 93件は旧 LaunchAgent（無効化済み .plist.disabled、/Volumes/SSD_USB_1/ ScreenShot Agent の checkout）の schema 3 vs 2 不一致。.ips は Homebrew Python 3.11 手動実行の SIGSEGV で無関係。
実測: footprint 33622 = 298MB（RSS 16MB）、親 190MB（RSS 30MB）。RSS は指標にならない、phys_footprint を使う。
保険が無い: 子 footprint の上限監視なし。psutil は windows extra のみ（pyproject.toml:25）。
サブタスク:
- I4-S1 新規 screen_context/memory.py: footprint_mb(pid)（libproc proc_pid_rusage RUSAGE_INFO_V2 の ri_phys_footprint）、limit_mb(env)（SCREEN_CONTEXT_INDEXER_MAX_MB、既定2048）。tests/test_memory.py。
- I4-S2 desktop.py Workers.poll で index 子の footprint > limit なら terminate→join(10)→may_restart なら restart、偽なら failed+stop。CommandProcess.pid 追加。last_restart_reason="memory"。tests/test_desktop.py。
- I4-S3 i18n menu.indexer.restarted 両カタログ、mac_app.py:106 周辺で表示。
- I4-S4 quick.child_env に SCREEN_CONTEXT_PARENT_PID、cli.py index --watch ループで getppid 不一致なら終了。tests/test_quick.py。
