"""Verify an Authenticode signature and its pinned leaf certificate for release CI."""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import subprocess
from pathlib import Path

_ALLOWED_STATUSES = {"Valid", "NotTrusted"}
_UNTRUSTED_ROOT_MESSAGE = "terminated in a root certificate which is not trusted"
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


def _signature_info(path: Path) -> dict[str, object]:
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "$securityModule = Join-Path $PSHOME "
        "'Modules\\Microsoft.PowerShell.Security\\Microsoft.PowerShell.Security.psd1'; "
        "Import-Module -Name $securityModule -Force; "
        "$s = Get-AuthenticodeSignature -LiteralPath $env:FACEHELLO_VERIFY_PATH; "
        "if ($null -eq $s.SignerCertificate) { $cert = '' } else { "
        "$cert = [Convert]::ToBase64String($s.SignerCertificate.RawData) }; "
        "$status = $s.Status.ToString(); "
        "$statusMessage = $s.StatusMessage; "
        "$timestamped = ($null -ne $s.TimeStamperCertificate); "
        "Write-Output $status; Write-Output $timestamped; Write-Output $cert; "
        "Write-Output $statusMessage"
    )
    env = os.environ.copy()
    env["FACEHELLO_VERIFY_PATH"] = str(path)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown PowerShell error"
        raise RuntimeError(f"could not inspect Authenticode signature: {detail}")
    lines = result.stdout.splitlines()
    if len(lines) < 4:
        raise RuntimeError("could not parse Authenticode signature information")
    return {
        "status": lines[0],
        "timestamped": lines[1].lower() == "true",
        "certificate": lines[2],
        "status_message": " ".join(lines[3:]),
    }


def verify(path: Path, expected_sha256: str) -> None:
    expected = expected_sha256.lower()
    if _SHA256_RE.fullmatch(expected) is None:
        raise ValueError("expected signer SHA-256 must contain 64 hexadecimal characters")
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    info = _signature_info(path)
    status = info.get("status")
    status_message = info.get("status_message")
    untrusted_root = (
        status == "UnknownError"
        and isinstance(status_message, str)
        and _UNTRUSTED_ROOT_MESSAGE in status_message.lower()
    )
    if status not in _ALLOWED_STATUSES and not untrusted_root:
        raise RuntimeError(f"invalid Authenticode signature status: {status}: {status_message}")
    encoded = info.get("certificate")
    if not isinstance(encoded, str) or not encoded:
        raise RuntimeError("Authenticode signer certificate is missing")
    certificate = base64.b64decode(encoded, validate=True)
    actual = hashlib.sha256(certificate).hexdigest()
    if actual != expected:
        raise RuntimeError(f"signer certificate mismatch: expected {expected}, got {actual}")
    if info.get("timestamped") is not True:
        raise RuntimeError("Authenticode signature is not timestamped")
    print(f"verified Authenticode signature ({status}, signer {actual})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--signer-sha256", required=True)
    args = parser.parse_args()
    verify(args.path, args.signer_sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
