<#
.SYNOPSIS
  生成一张「自签名」代码签名证书,供 FaceHello 在开发机 / VM 里端到端验证签名管道。

.DESCRIPTION
  产出:
    scripts\sign\out\FaceHello-Dev.pfx   私钥(签名用,带密码;已被 .gitignore 忽略)
    scripts\sign\out\FaceHello-Dev.cer   公钥证书(装到测试机的信任库用)

  自签名只能证明「签名后没被篡改」+ 让「装了这张根证书的机器」信任本程序;
  它【不能】消除别人下载时的 SmartScreen「未知发布者」警告。要面向真实用户分发,
  换成 Azure Trusted Signing 或 EV 证书即可 —— 签名管道(本脚本之外的 build_release /
  Inno SignTool)不用动,只换证书来源。

  -Trust 开关会把公钥装进【本机】的「受信任的根」与「受信任的发布者」,这样在本机 /
  VM 上 `signtool verify /pa` 和资源管理器属性页都会显示签名有效。需【管理员】终端。

.EXAMPLE
  # 1) 普通终端:只建证书 + 导出 pfx/cer
  powershell -ExecutionPolicy Bypass -File scripts\sign\setup_selfsigned.ps1

  # 2) 管理员终端:建证书并让本机信任它(VM 里测 CP / 安装器前先跑这个)
  powershell -ExecutionPolicy Bypass -File scripts\sign\setup_selfsigned.ps1 -Trust
#>
param(
    [string]$Subject  = "CN=FaceHello Dev (self-signed)",
    [string]$Password = "facehello",
    [string]$OutDir   = "$PSScriptRoot\out",
    [switch]$Trust
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$cert = New-SelfSignedCertificate `
    -Type CodeSigningCert `
    -Subject $Subject `
    -CertStoreLocation Cert:\CurrentUser\My `
    -KeyExportPolicy Exportable `
    -KeyUsage DigitalSignature `
    -KeySpec Signature `
    -NotAfter (Get-Date).AddYears(5)

$pfx = Join-Path $OutDir "FaceHello-Dev.pfx"
$cer = Join-Path $OutDir "FaceHello-Dev.cer"
$sec = ConvertTo-SecureString -String $Password -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $sec | Out-Null
Export-Certificate    -Cert $cert -FilePath $cer | Out-Null

Write-Host ""
Write-Host "已生成自签名代码签名证书:"
Write-Host "  PFX (私钥,签名用) : $pfx"
Write-Host "  CER (公钥,信任用) : $cer"
Write-Host "  Thumbprint         : $($cert.Thumbprint)"
Write-Host "  密码               : $Password"

if ($Trust) {
    Import-Certificate -FilePath $cer -CertStoreLocation Cert:\LocalMachine\Root          | Out-Null
    Import-Certificate -FilePath $cer -CertStoreLocation Cert:\LocalMachine\TrustedPublisher | Out-Null
    Write-Host ""
    Write-Host "已装入本机「受信任的根」+「受信任的发布者」,本机签名校验现在会通过。"
} else {
    Write-Host ""
    Write-Host "提示:要让本机信任此证书(校验通过),用【管理员】终端重跑并加 -Trust,"
    Write-Host "      或手动:Import-Certificate -FilePath `"$cer`" -CertStoreLocation Cert:\LocalMachine\Root"
}
