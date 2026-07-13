@echo off
if not defined SIGNTOOL (
  echo SIGNTOOL is not set 1>&2
  exit /b 2
)
"%SIGNTOOL%" sign /fd SHA256 /f "%FACEHELLO_SIGN_PFX%" /p "%FACEHELLO_SIGN_PASS%" /tr http://timestamp.digicert.com /td SHA256 %*
