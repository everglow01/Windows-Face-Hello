"""Verify an Authenticode signature and its pinned leaf certificate for release CI."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
from pathlib import Path

_ALLOWED_STATUSES = {"Valid", "NotTrusted"}
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


def _signature_info(path: Path) -> dict[str, object]:
    script = (
        "$s = Get-AuthenticodeSignature -LiteralPath $args[0]; "
        "$cert = if ($null -eq $s.SignerCertificate) { '' } else { "
        "[Convert]::ToBase64String($s.SignerCertificate.RawData) }; "
        "[pscustomobject]@{ status = $s.Status.ToString(); certificate = $cert; "
        "timestamped = ($null -ne $s.TimeStamperCertificate) } | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script, str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def verify(path: Path, expected_sha256: str) -> None:
    expected = expected_sha256.lower()
    if _SHA256_RE.fullmatch(expected) is None:
        raise ValueError("expected signer SHA-256 must contain 64 hexadecimal characters")
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    info = _signature_info(path)
    status = info.get("status")
    if status not in _ALLOWED_STATUSES:
        raise RuntimeError(f"invalid Authenticode signature status: {status}")
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
