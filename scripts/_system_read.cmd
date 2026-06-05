@echo off
rem 以 SYSTEM 身份读取 LSA Secret(由计划任务调用)。%~dp0.. = 项目根
rem 输出写到 C:\Windows\Temp(SYSTEM 必可写),避免 OneDrive 路径权限/同步问题
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m scripts.cred_vault_cli get owen --show > "C:\Windows\Temp\facehello_sysread.txt" 2>&1
