@echo off
rem Run the camera probe as SYSTEM / session 0 (session-0 precheck) via psexec.
rem Needs PSTools\psexec.exe under the repo root.
rem Usage from repo root:  scripts\run_session0_probe.cmd
setlocal
set "ROOT=%~dp0.."
"%ROOT%\PSTools\psexec.exe" -s -accepteula "%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\cam_session0_probe.py"
endlocal
