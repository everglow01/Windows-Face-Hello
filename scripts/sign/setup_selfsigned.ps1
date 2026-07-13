<#
.SYNOPSIS
  Generate a self-signed code-signing certificate for FaceHello releases.

.DESCRIPTION
  Outputs:
    scripts\sign\out\FaceHello-Dev.pfx   Private key used for signing (password protected).
    scripts\sign\out\FaceHello-Dev.cer   Public certificate used for trust installation.

  A self-signed certificate proves that signed files were not modified. It is trusted only
  on machines where its public certificate has been installed. The -Trust switch installs
  the public certificate into LocalMachine Root and TrustedPublisher and requires an
  elevated PowerShell session.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\sign\setup_selfsigned.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\sign\setup_selfsigned.ps1 -Trust
#>
param(
    [string]$Subject = "CN=FaceHello Dev (self-signed)",
    [string]$Password = "facehello",
    [string]$OutDir = "$PSScriptRoot\out",
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
Export-Certificate -Cert $cert -FilePath $cer | Out-Null

Write-Host ""
Write-Host "Generated self-signed code-signing certificate:"
Write-Host "  PFX (private key): $pfx"
Write-Host "  CER (public cert): $cer"
Write-Host "  Thumbprint:        $($cert.Thumbprint)"
Write-Host "  PFX password:      $Password"

if ($Trust) {
    Import-Certificate -FilePath $cer -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
    Import-Certificate -FilePath $cer -CertStoreLocation Cert:\LocalMachine\TrustedPublisher | Out-Null
    Write-Host ""
    Write-Host "Installed the certificate in LocalMachine Root and TrustedPublisher."
} else {
    Write-Host ""
    Write-Host "To trust this certificate locally, rerun this script as administrator with -Trust."
}
