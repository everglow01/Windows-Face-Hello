@echo off
rem Target for a SYSTEM scheduled task that fires while the screen is LOCKED.
rem The task already runs as SYSTEM, so no psexec here -- just run the probe.
rem Register (path has no spaces, no inner quotes needed):
rem   schtasks /create /tn FaceCamProbe /ru SYSTEM /rl HIGHEST /f /sc minute /mo 1 /tr %~f0
rem Then Win+L, wait ~2 min, unlock, inspect C:\FaceHelloProbe\probe.log.
rem Cleanup:  schtasks /delete /tn FaceCamProbe /f
setlocal
set "ROOT=%~dp0.."
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\cam_session0_probe.py"
endlocal
