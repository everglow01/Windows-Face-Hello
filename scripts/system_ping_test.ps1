# 以 SYSTEM 身份 ping 认证服务管道的验证脚本(在管理员 PowerShell 运行)。
# 前提:认证服务(python -m face_hello.service)已在另一处运行并监听管道。
# 用 Register-ScheduledTask 以 NT AUTHORITY\SYSTEM 跑 _system_ping.cmd,输出写到 Temp 再读回。
$ErrorActionPreference = "Stop"
$cmd = Join-Path $PSScriptRoot "_system_ping.cmd"
$out = "C:\Windows\Temp\facehello_sysping.txt"
if (Test-Path $out) { Remove-Item $out -Force }

$action    = New-ScheduledTaskAction -Execute "cmd.exe" -Argument ('/c "' + $cmd + '"')
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName FaceHelloSysPing -Action $action -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName FaceHelloSysPing

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-Path $out) { Start-Sleep -Milliseconds 500; break }
}

$info = Get-ScheduledTaskInfo -TaskName FaceHelloSysPing
Write-Host ("LastTaskResult: 0x{0:X} ({0})" -f $info.LastTaskResult)
Write-Host "===== SYSTEM ping 输出(期望 {`"ok`": true, ... `"users`": [`"owen`"]}) ====="
if (Test-Path $out) { Get-Content $out -Encoding UTF8 } else { Write-Host "(无输出文件)" }

Unregister-ScheduledTask -TaskName FaceHelloSysPing -Confirm:$false
if (Test-Path $out) { Remove-Item $out -Force }
