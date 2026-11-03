# #72 計画要約（planner、事実は抜き取り確認済み）
aw_context.py: aw_get が唯一の AW アクセス（GET）、--from/--to か --last 必須、フォールバックなし、--last と --from/--to 同時指定は --last が黙って勝つ。service.get_activity_between: Unix 秒、[start,end)、7日、limit 1-50、more、監査行 fail closed、untrusted envelope。
I1: A1 新 aw_range.py（--start/--end 必須、ISO か Unix 秒、AW 非接続、get_activity_between 1回）、A2 aw_context の同時指定拒否、A3 4点境界（service・aw_range・aw_context）、A4 AW 読み取り専用（data None、GET、読み取りパス、範囲）、A5 aw_range の実 MCP 経路
I2: B1 README 節追加、B2 README.ja.md 新規、B3 一時環境で再現（偽 AW、5600 以外）、B4 CHANGELOG、B5 #1473 返信案（英語、送信しない）
採用（推奨案）: (a) aw_range.py、--last 残し同時指定拒否、examples は i18n 対象外、ISO と Unix 秒、返信は英語案のみ、実機確認は任意
