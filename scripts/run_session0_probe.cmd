@echo off
rem 以 SYSTEM / session 0 跑摄像头探针(session 0 预检)。
rem 需要 PSTools\psexec.exe 放在仓库根目录下的 PSTools\ 里。
rem 用法:仓库根目录执行  scripts\run_session0_probe.cmd
setlocal
set "ROOT=%~dp0.."
"%ROOT%\PSTools\psexec.exe" -s -accepteula "%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\cam_session0_probe.py"
endlocal
