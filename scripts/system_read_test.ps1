# 以 SYSTEM 身份读取 LSA Secret 的验证脚本(在管理员 PowerShell 运行)。
# 用 Register-ScheduledTask 以 NT AUTHORITY\SYSTEM 跑 _system_read.cmd,输出写到 Temp 再读回。
$ErrorActionPreference = "Stop"
$cmd = Join-Path $PSScriptRoot "_system_read.cmd"
$out = "C:\Windows\Temp\facehello_sysread.txt"
if (Test-Path $out) { Remove-Item $out -Force }

$action    = New-ScheduledTaskAction -Execute "cmd.exe" -Argument ('/c "' + $cmd + '"')
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName FaceHelloSysRead -Action $action -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName FaceHelloSysRead

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-Path $out) { Start-Sleep -Milliseconds 500; break }
}

$info = Get-ScheduledTaskInfo -TaskName FaceHelloSysRead
Write-Host ("LastTaskResult: 0x{0:X} ({0})" -f $info.LastTaskResult)
Write-Host "===== SYSTEM 读取输出 ====="
if (Test-Path $out) { Get-Content $out -Encoding Default } else { Write-Host "(无输出文件)" }

Unregister-ScheduledTask -TaskName FaceHelloSysRead -Confirm:$false
if (Test-Path $out) { Remove-Item $out -Force }
