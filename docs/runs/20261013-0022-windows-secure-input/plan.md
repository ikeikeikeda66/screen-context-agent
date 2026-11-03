# Windows secure_input 計画要約
事実: windows.py:43-44 コメントのみ。spike は comtypes（GetModule で comtypes.gen 生成）、COMError で fail-open。実機は #3 で Edge の IsPassword=True のみ確認、Chrome・Win32・コスト・frozen 未確認。comtypes は windows extra に無い。
I1: 方式 (a) comtypes 追加 vs (b) ctypes 生 COM vtable、COM 初期化（MTA、RPC_E_CHANGED_MODE）、UIA 不可環境（案A 永久停止 / 案B 生成失敗のみ False）、フォーカスなし（False）。tests/test_windows_secure_input.py。
I2: README/CHANGELOG/ARCHITECTURE/WINDOWS.md、実機確認 issue 下書き。
要判断: UIA 不可環境の扱い、方式。
## I1 結果・ユーザー決定（2026-10-13）
方式 (b) ctypes 生 vtable（GetFocusedElement=8、get_CurrentIsPassword=35、Release=2、Wine IDL / mingw-w64 / zigwin32 の3資料一致）。UIA 不可は案A（毎回 raise、成功のみキャッシュ、再試行）。フォーカスなし False、HRESULT 失敗 raise。COM は MTA、S_OK/S_FALSE/RPC_E_CHANGED_MODE 成功扱い。64bit 以外は UiaError。
