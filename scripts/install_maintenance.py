"""安装器调用的升级收尾：配置服务、切换 CP、等待服务就绪。"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import winreg
from pathlib import Path

from face_hello import config, probes
from face_hello.version import display_version, get_build_info

_CLSID = "{E071A7CE-5D7F-4063-9A10-AE39AEC64EE8}"
_CP_KEY = rf"CLSID\{_CLSID}\InprocServer32"
_CERT_NAME = "FaceHello-Signer.cer"


def _certificate_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _store_contains(store: str, digest: str) -> bool:
    script = (
        "$want = $env:FACEHELLO_CERT_DIGEST; $store = $env:FACEHELLO_CERT_STORE; "
        "$sha = [Security.Cryptography.SHA256]::Create(); "
        "try { foreach ($cert in Get-ChildItem $store) { "
        "$got = ([BitConverter]::ToString($sha.ComputeHash($cert.RawData))).Replace('-', '').ToLowerInvariant(); "
        "if ($got -eq $want) { exit 0 } } } finally { $sha.Dispose() }; exit 1"
    )
    env = os.environ.copy()
    env["FACEHELLO_CERT_DIGEST"] = digest
    env["FACEHELLO_CERT_STORE"] = store
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], env=env
    )
    return result.returncode == 0


def _trust_marker(store: str, digest: str) -> Path:
    safe_store = store.rsplit("\\", 1)[-1].lower()
    return config.DATA_DIR / f"signer-{safe_store}-{digest}.installed"


def _import_signer(root: Path, allowed_signers: tuple[str, ...]) -> list[Path]:
    added_markers = []
    certificate = root / _CERT_NAME
    if not certificate.is_file():
        if allowed_signers:
            raise FileNotFoundError(certificate)
        return added_markers
    digest = _certificate_sha256(certificate)
    if digest not in allowed_signers:
        raise RuntimeError("signing certificate does not match build info")
    for store, certutil_store in (
        (r"Cert:\LocalMachine\Root", "Root"),
        (r"Cert:\LocalMachine\TrustedPublisher", "TrustedPublisher"),
    ):
        if not _store_contains(store, digest):
            _run("certutil.exe", "-addstore", "-f", certutil_store, str(certificate))
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            marker = _trust_marker(store, digest)
            marker.touch()
            added_markers.append(marker)
    return added_markers



def _remove_certificate_by_digest(store: str, digest: str) -> None:
    script = (
        "$want = $env:FACEHELLO_CERT_DIGEST; $store = $env:FACEHELLO_CERT_STORE; "
        "$sha = [Security.Cryptography.SHA256]::Create(); "
        "try { foreach ($cert in Get-ChildItem $store) { "
        "$got = ([BitConverter]::ToString($sha.ComputeHash($cert.RawData))).Replace('-', '').ToLowerInvariant(); "
        "if ($got -eq $want) { Remove-Item -LiteralPath $cert.PSPath -Force } } } "
        "finally { $sha.Dispose() }"
    )
    env = os.environ.copy()
    env["FACEHELLO_CERT_DIGEST"] = digest
    env["FACEHELLO_CERT_STORE"] = store
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        env=env,
    )


def _rollback_signer(markers: list[Path]) -> None:
    for marker in markers:
        parts = marker.stem.split("-")
        if len(parts) < 3:
            continue
        store_name = parts[1]
        digest = parts[2]
        store = (
            r"Cert:\LocalMachine\TrustedPublisher"
            if store_name == "trustedpublisher"
            else r"Cert:\LocalMachine\Root"
        )
        _remove_certificate_by_digest(store, digest)
        marker.unlink(missing_ok=True)


def _remove_signer(root: Path, allowed_signers: tuple[str, ...]) -> None:
    certificate = root / _CERT_NAME
    if not certificate.is_file():
        return
    digest = _certificate_sha256(certificate)
    if digest not in allowed_signers:
        raise RuntimeError("refusing to remove unexpected signing certificate")
    for store in (r"Cert:\LocalMachine\Root", r"Cert:\LocalMachine\TrustedPublisher"):
        marker = _trust_marker(store, digest)
        if marker.exists():
            _remove_certificate_by_digest(store, digest)
            marker.unlink()


def _run(*args: str) -> None:
    subprocess.run(args, check=True)


def _registered_cp() -> Path | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, _CP_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, None)
    except FileNotFoundError:
        return None
    return Path(value).resolve() if isinstance(value, str) and value else None


def _owned_cp(path: Path | None, root: Path) -> bool:
    if path is None:
        return False
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return False
    name = path.name
    return (
        (name == "FaceHelloCP.dll" or name.startswith("FaceHelloCP-"))
        and path.suffix.lower() == ".dll"
    )


def _register(path: Path) -> None:
    _run("regsvr32.exe", "/s", str(path))


def _unregister(path: Path) -> None:
    if path.exists():
        _run("regsvr32.exe", "/s", "/u", str(path))


def _wait_ready(version: str, timeout: float = 120) -> None:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = probes.call_pipe({"cmd": "ping"})
            if (
                response.get("ok") is True
                and response.get("ready") is True
                and response.get("version") == version
                and response.get("protocol") == 1
            ):
                return
        except Exception:  # noqa: BLE001 服务预热期间连接失败是预期状态
            pass
        time.sleep(1)
    raise RuntimeError("FaceHello service did not become ready")


def configure(service_command: str, should_start: bool) -> None:
    root = config.INSTALL_ROOT.resolve()
    version = display_version()
    build_info = get_build_info()
    new_cp = root / f"FaceHelloCP-{version}.dll"
    if not new_cp.is_file():
        raise FileNotFoundError(new_cp)
    old_cp = _registered_cp()
    if old_cp is not None and not _owned_cp(old_cp, root):
        raise RuntimeError(f"registered CP is outside install root: {old_cp}")

    added_trust: list[Path] = []
    try:
        added_trust = _import_signer(root, build_info.signer_sha256)
        (root / ".installed").touch()
        _run(
            "icacls.exe",
            str(config.AVATAR_DIR),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(OI)(CI)F",
            "/T",
            "/C",
        )
        _run(
            sys.executable,
            str(root / "winservice_main.py"),
            "--startup",
            "auto",
            service_command,
        )
        _register(new_cp)
        if should_start:
            _run(sys.executable, str(root / "winservice_main.py"), "start")
            _wait_ready(version)
    except Exception:
        try:
            _unregister(new_cp)
            if old_cp is not None and old_cp != new_cp and old_cp.exists():
                _register(old_cp)
            if should_start:
                _run(sys.executable, str(root / "winservice_main.py"), "start")
            _rollback_signer(added_trust)
        except Exception:  # noqa: BLE001 保留原始升级异常
            pass
        raise


def unregister_current() -> None:
    root = config.INSTALL_ROOT.resolve()
    current = _registered_cp()
    if current is None:
        return
    if not _owned_cp(current, root):
        raise RuntimeError(f"refusing to unregister CP outside install root: {current}")
    _unregister(current)


def uninstall() -> None:
    root = config.INSTALL_ROOT.resolve()
    build_info = get_build_info()
    unregister_current()
    _remove_signer(root, build_info.signer_sha256)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    configure_parser = sub.add_parser("configure")
    configure_parser.add_argument("--service-command", choices=("install", "update"), required=True)
    configure_parser.add_argument("--start", choices=("yes", "no"), required=True)
    sub.add_parser("uninstall")
    args = parser.parse_args()
    if args.command == "configure":
        configure(args.service_command, args.start == "yes")
    else:
        uninstall()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
