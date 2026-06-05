@echo off
rem 以 SYSTEM 身份 ping 认证服务命名管道(由计划任务调用)。%~dp0.. = 项目根
rem 验证锁屏场景下 CP(SYSTEM)能否连上服务;输出写到 C:\Windows\Temp(SYSTEM 必可写)
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m scripts.auth_client ping > "C:\Windows\Temp\facehello_sysping.txt" 2>&1
