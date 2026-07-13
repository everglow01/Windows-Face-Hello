"""安装器调用的升级收尾：配置服务、切换 CP、等待服务就绪。"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import winreg
from pathlib import Path

import ntsecuritycon
import pywintypes
import win32api
import win32con
import win32file
import win32security
import win32service

from face_hello import config, probes
from face_hello.version import display_version, get_build_info

_CLSID = "{E071A7CE-5D7F-4063-9A10-AE39AEC64EE8}"
_CP_KEY = rf"CLSID\{_CLSID}\InprocServer32"
_CERT_NAME = "FaceHello-Signer.cer"
_COMMAND_TIMEOUT = 60
_BACKUP_DIR_NAME = "update-backup"


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
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env=env,
        timeout=_COMMAND_TIMEOUT,
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
    try:
        for store, certutil_store in (
            (r"Cert:\LocalMachine\Root", "Root"),
            (r"Cert:\LocalMachine\TrustedPublisher", "TrustedPublisher"),
        ):
            if not _store_contains(store, digest):
                _run("certutil.exe", "-addstore", "-f", certutil_store, str(certificate))
                config.DATA_DIR.mkdir(parents=True, exist_ok=True)
                marker = _trust_marker(store, digest)
                added_markers.append(marker)
                marker.touch()
    except Exception:
        _rollback_signer(added_markers)
        raise
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
        timeout=_COMMAND_TIMEOUT,
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
        try:
            _remove_certificate_by_digest(store, digest)
        finally:
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


def _run(*args: str, timeout: int = _COMMAND_TIMEOUT) -> None:
    subprocess.run(args, check=True, timeout=timeout)


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = win32file.GetFileAttributes(str(path))
    except pywintypes.error as exc:
        raise RuntimeError(
            f"cannot inspect runtime data ACL target {path}: winerror={exc.winerror}"
        ) from exc
    return bool(attributes & win32con.FILE_ATTRIBUTE_REPARSE_POINT)


def _runtime_acl_targets(root: Path):
    if _is_reparse_point(root):
        raise RuntimeError(f"refusing to follow runtime data reparse point: {root}")
    yield root

    def descendants(directory: Path):
        try:
            children = sorted(directory.iterdir(), key=lambda path: path.name.lower())
        except OSError as exc:
            raise RuntimeError(
                f"cannot enumerate runtime data ACL target {directory}: {exc}"
            ) from exc
        for child in children:
            if directory == root and child.name.casefold() == _BACKUP_DIR_NAME:
                continue
            if _is_reparse_point(child):
                raise RuntimeError(
                    f"refusing to follow runtime data reparse point: {child}"
                )
            yield child
            if child.is_dir():
                yield from descendants(child)

    yield from descendants(root)


def _runtime_dacl(is_directory: bool):
    system_sid = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid)
    admins_sid = win32security.CreateWellKnownSid(
        win32security.WinBuiltinAdministratorsSid
    )
    flags = 0
    if is_directory:
        flags = win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE
    dacl = win32security.ACL()
    for sid in (system_sid, admins_sid):
        dacl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION,
            flags,
            ntsecuritycon.FILE_ALL_ACCESS,
            sid,
        )
    return dacl, admins_sid


def _set_runtime_dacl(path: Path, is_directory: bool) -> None:
    dacl, _admins_sid = _runtime_dacl(is_directory)
    win32security.SetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION
        | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        dacl,
        None,
    )


def _take_ownership(path: Path, is_directory: bool) -> None:
    dacl, admins_sid = _runtime_dacl(is_directory)
    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(),
        win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY,
    )
    privileges = [
        win32security.LookupPrivilegeValue(
            None, win32security.SE_TAKE_OWNERSHIP_NAME
        ),
        win32security.LookupPrivilegeValue(None, win32security.SE_RESTORE_NAME),
    ]
    try:
        win32security.AdjustTokenPrivileges(
            token,
            False,
            [(privilege, win32con.SE_PRIVILEGE_ENABLED) for privilege in privileges],
        )
        win32security.SetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION,
            admins_sid,
            None,
            None,
            None,
        )
        win32security.SetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION
            | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            dacl,
            None,
        )
    finally:
        win32security.AdjustTokenPrivileges(
            token, False, [(privilege, 0) for privilege in privileges]
        )
        token.Close()


def _repair_runtime_acl() -> None:
    root = Path(os.path.abspath(config.AVATAR_DIR))
    data_dir = Path(os.path.abspath(config.DATA_DIR))
    try:
        data_dir.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"runtime data directory is outside FaceHello root: {data_dir}") from exc
    if root.exists() and _is_reparse_point(root):
        raise RuntimeError(f"refusing to follow runtime data reparse point: {root}")
    root.mkdir(parents=True, exist_ok=True)
    try:
        _set_runtime_dacl(root, True)
    except pywintypes.error as exc:
        if getattr(exc, "winerror", None) != 5:
            raise RuntimeError(
                f"cannot repair runtime data ACL {root}: winerror={exc.winerror}"
            ) from exc
        try:
            _take_ownership(root, True)
        except pywintypes.error as recovery_exc:
            raise RuntimeError(
                f"cannot recover runtime data ACL {root}: winerror={recovery_exc.winerror}"
            ) from recovery_exc
    if data_dir.exists() and _is_reparse_point(data_dir):
        raise RuntimeError(f"refusing to follow runtime data reparse point: {data_dir}")
    data_dir.mkdir(parents=True, exist_ok=True)
    for path in _runtime_acl_targets(root):
        if path == root:
            continue
        is_directory = path.is_dir()
        try:
            _set_runtime_dacl(path, is_directory)
        except pywintypes.error as exc:
            if getattr(exc, "winerror", None) != 5:
                raise RuntimeError(
                    f"cannot repair runtime data ACL {path}: winerror={exc.winerror}"
                ) from exc
            try:
                _take_ownership(path, is_directory)
            except pywintypes.error as recovery_exc:
                raise RuntimeError(
                    "cannot recover runtime data ACL "
                    f"{path}: winerror={recovery_exc.winerror}"
                ) from recovery_exc
    log_path = data_dir / "service.log"
    try:
        with log_path.open("a", encoding="utf-8"):
            pass
    except OSError as exc:
        winerror = getattr(exc, "winerror", None)
        raise RuntimeError(
            f"cannot append service log {log_path}: winerror={winerror or exc.errno}"
        ) from exc


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


def _service_status() -> dict | None:
    scm = None
    service = None
    try:
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        service = win32service.OpenService(
            scm, config.SERVICE_NAME, win32service.SERVICE_QUERY_STATUS
        )
        return win32service.QueryServiceStatusEx(service)
    except pywintypes.error as exc:
        if getattr(exc, "winerror", None) == 1060:
            return None
        raise
    finally:
        if service is not None:
            win32service.CloseServiceHandle(service)
        if scm is not None:
            win32service.CloseServiceHandle(scm)


def _stop_service(root: Path, timeout: float = 30) -> None:
    import time

    status = _service_status()
    if status is None or status["CurrentState"] == win32service.SERVICE_STOPPED:
        return
    try:
        _run(sys.executable, str(root / "winservice_main.py"), "stop")
    except subprocess.CalledProcessError:
        status = _service_status()
        if status is None or status["CurrentState"] == win32service.SERVICE_STOPPED:
            return
        raise
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = _service_status()
        if status is None or status["CurrentState"] == win32service.SERVICE_STOPPED:
            return
        time.sleep(0.5)
    raise RuntimeError("FaceHello service did not stop during cleanup")


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
        status = _service_status()
        if status is None:
            raise RuntimeError("FaceHello service is not installed")
        if status["CurrentState"] == win32service.SERVICE_STOPPED:
            raise RuntimeError(
                "FaceHello service stopped before ready "
                f"(win32={status['Win32ExitCode']}, "
                f"service={status['ServiceSpecificExitCode']})"
            )
        time.sleep(1)
    raise RuntimeError("FaceHello service remained alive but did not become ready")


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
    service_configured = False
    new_cp_registered = False
    service_start_attempted = False
    try:
        (root / ".installed").touch()
        _repair_runtime_acl()
        added_trust = _import_signer(root, build_info.signer_sha256)
        service_configured = True
        _run(
            sys.executable,
            str(root / "winservice_main.py"),
            "--startup",
            "auto",
            service_command,
        )
        new_cp_registered = True
        _register(new_cp)
        if should_start:
            service_start_attempted = True
            _run(sys.executable, str(root / "winservice_main.py"), "start")
            _wait_ready(version)
    except Exception:
        try:
            if service_start_attempted:
                _stop_service(root)
        except Exception:  # noqa: BLE001 继续完成其余回滚
            pass
        try:
            if new_cp_registered:
                _unregister(new_cp)
            if old_cp is not None and old_cp != new_cp and old_cp.exists():
                _register(old_cp)
        except Exception:  # noqa: BLE001 继续完成其余回滚
            pass
        try:
            if service_command == "install" and service_configured:
                _run(sys.executable, str(root / "winservice_main.py"), "remove")
        except Exception:  # noqa: BLE001 继续完成 signer 回滚
            pass
        try:
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
