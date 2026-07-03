from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import config, cred_vault
from .i18n import t
from .store import FaceStore

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_INFO = "info"

_CP_CLSID = "{E071A7CE-5D7F-4063-9A10-AE39AEC64EE8}"
_MAX_LOG_LINES = 30


@dataclass
class DiagnosticItem:
    name: str
    status: str
    detail: str
    advice: str = ""


@dataclass
class DiagnosticReport:
    started_at: datetime
    mode: str
    user: str
    is_admin: bool
    items: list[DiagnosticItem] = field(default_factory=list)

    @property
    def overall_status(self) -> str:
        statuses = {item.status for item in self.items}
        if STATUS_FAIL in statuses:
            return STATUS_FAIL
        if STATUS_WARN in statuses:
            return STATUS_WARN
        return STATUS_OK

    def to_text(self, lang: str = "zh") -> str:
        lines = [
            "FaceHello Diagnostics",
            f"Time: {self.started_at.isoformat(timespec='seconds')}",
            f"Mode: {self.mode}",
            f"Current user: {self.user}",
            f"Administrator: {_yes_no(self.is_admin, lang)}",
            f"Overall: {status_label(self.overall_status, lang)}",
            "",
            "Items:",
        ]
        for item in self.items:
            lines.append(f"- [{status_label(item.status, lang)}] {item.name}: {item.detail}")
            if item.advice:
                lines.append(f"  Advice: {item.advice}")
        return "\n".join(lines)


def status_label(status: str, lang: str = "zh") -> str:
    key = {
        STATUS_OK: "diag_status_ok",
        STATUS_WARN: "diag_status_warn",
        STATUS_FAIL: "diag_status_fail",
        STATUS_INFO: "diag_status_info",
    }.get(status, "diag_status_info")
    return t(key, lang)


def run_diagnostics(lang: str = "zh", progress: Callable[[str], None] | None = None) -> DiagnosticReport:
    user = cred_vault.current_user()
    report = DiagnosticReport(
        started_at=datetime.now(),
        mode=t("diag_mode_installed" if config.IS_INSTALLED else "diag_mode_dev", lang),
        user=user,
        is_admin=_is_admin(),
    )

    _run_check(report, lang, progress, "diag_step_environment", _check_environment)
    _run_check(report, lang, progress, "diag_step_store", _check_store, user)
    _run_check(report, lang, progress, "diag_step_password", _check_password, user)
    _run_check(report, lang, progress, "diag_step_service", _check_service)
    _run_check(report, lang, progress, "diag_step_pipe", _check_pipe)
    _run_check(report, lang, progress, "diag_step_cp", _check_cp)
    _run_check(report, lang, progress, "diag_step_models", _check_models)
    _run_check(report, lang, progress, "diag_step_camera", _check_camera)
    _run_check(report, lang, progress, "diag_step_log", _check_log)
    return report


def _run_check(report: DiagnosticReport, lang: str, progress: Callable[[str], None] | None,
               key: str, func, *args) -> None:
    if progress:
        progress(t(key, lang))
    try:
        func(report, lang, *args)
    except Exception as exc:
        report.items.append(DiagnosticItem(t(key, lang), STATUS_FAIL, str(exc)))


def _add(report: DiagnosticReport, lang: str, name_key: str, status: str, detail: str,
         advice_key: str = "") -> None:
    advice = t(advice_key, lang) if advice_key else ""
    report.items.append(DiagnosticItem(t(name_key, lang), status, detail, advice))


def _yes_no(value: bool, lang: str) -> str:
    return t("diag_yes" if value else "diag_no", lang)


def _is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _check_environment(report: DiagnosticReport, lang: str) -> None:
    _add(
        report, lang, "diag_item_environment", STATUS_INFO,
        t(
            "diag_environment_detail", lang,
            mode=report.mode,
            root=config.ROOT,
            data=config.DATA_DIR,
            models=config.MODELS_DIR,
            cp=config.CP_DLL,
        ),
    )
    _add(
        report, lang, "diag_item_admin", STATUS_OK if report.is_admin else STATUS_WARN,
        t("diag_admin_detail", lang, admin=_yes_no(report.is_admin, lang)),
        "" if report.is_admin else "diag_advice_run_admin",
    )


def _check_store(report: DiagnosticReport, lang: str, user: str) -> None:
    try:
        store = FaceStore().load()
        profiles = store.list_profiles()
    except Exception as exc:
        _add(report, lang, "diag_item_store", STATUS_FAIL, t("diag_store_read_fail", lang, e=exc))
        return

    names = list(dict.fromkeys(p.name for p in profiles))
    if not profiles:
        _add(report, lang, "diag_item_store", STATUS_FAIL, t("diag_store_empty", lang),
             "diag_advice_enroll_current_user")
        return
    if user not in names:
        _add(
            report, lang, "diag_item_store", STATUS_WARN,
            t("diag_store_missing_user", lang, user=user, users=", ".join(names)),
            "diag_advice_enroll_current_user",
        )
        return
    _add(
        report, lang, "diag_item_store", STATUS_OK,
        t("diag_store_ok", lang, count=len(profiles), users=", ".join(names)),
    )


def _check_password(report: DiagnosticReport, lang: str, user: str) -> None:
    try:
        readable = bool(cred_vault.retrieve_password(user))
    except Exception:
        readable = False
    _add(
        report, lang, "diag_item_password",
        STATUS_OK if readable else STATUS_WARN,
        t("diag_password_detail", lang, readable=_yes_no(readable, lang)),
        "" if readable else "diag_advice_password_admin",
    )


def _check_service(report: DiagnosticReport, lang: str) -> None:
    try:
        import win32con
        import win32service
        import win32serviceutil

        status = win32serviceutil.QueryServiceStatus("FaceHello")[1]
        scm = None
        svc = None
        try:
            scm = win32service.OpenSCManager(None, None, win32con.GENERIC_READ)
            svc = win32service.OpenService(scm, "FaceHello", win32service.SERVICE_QUERY_CONFIG)
            cfg = win32service.QueryServiceConfig(svc)
        finally:
            if svc is not None:
                win32service.CloseServiceHandle(svc)
            if scm is not None:
                win32service.CloseServiceHandle(scm)
        start_type = cfg[1]
        account = cfg[7]
        image_path = cfg[3]
    except Exception as exc:
        _add(report, lang, "diag_item_service", STATUS_FAIL,
             t("diag_service_missing", lang, e=exc), "diag_advice_install_service")
        return

    running = status == 4
    auto = start_type == 2
    path_ok = str(config.ROOT) in image_path or str(config.INSTALL_ROOT) in image_path
    status_key = {1: "svc_stopped", 2: "svc_starting", 3: "svc_stopping", 4: "svc_running",
                  7: "svc_paused"}.get(status)
    status_text = t(status_key, lang) if status_key else t("svc_code", lang, st=status)
    item_status = STATUS_OK if running and auto and path_ok else STATUS_WARN
    advice = "" if item_status == STATUS_OK else "diag_advice_service"
    _add(
        report, lang, "diag_item_service", item_status,
        t("diag_service_detail", lang, status=status_text,
          start=t("diag_start_auto" if auto else "diag_start_other", lang),
          account=account, path=image_path),
        advice,
    )


def _check_pipe(report: DiagnosticReport, lang: str) -> None:
    try:
        import win32file
        import win32pipe

        handle = win32file.CreateFile(
            config.PIPE_NAME,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0, None, win32file.OPEN_EXISTING, 0, None,
        )
    except Exception as exc:
        winerror = getattr(exc, "winerror", None)
        if winerror == 5:
            _add(report, lang, "diag_item_pipe", STATUS_WARN, t("diag_pipe_denied", lang),
                 "diag_advice_run_admin")
        elif winerror == 2:
            _add(report, lang, "diag_item_pipe", STATUS_FAIL, t("diag_pipe_missing", lang),
                 "diag_advice_start_service")
        else:
            _add(report, lang, "diag_item_pipe", STATUS_FAIL, t("diag_pipe_connect_fail", lang, e=exc),
                 "diag_advice_start_service")
        return
    try:
        win32pipe.SetNamedPipeHandleState(handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)
        win32file.WriteFile(handle, json.dumps({"cmd": "ping"}).encode("utf-8"))
        resp = json.loads(win32file.ReadFile(handle, 65536)[1].decode("utf-8"))
    except Exception as exc:
        _add(report, lang, "diag_item_pipe", STATUS_FAIL, t("diag_pipe_ping_fail", lang, e=exc))
        return
    finally:
        win32file.CloseHandle(handle)

    if resp.get("ok"):
        users = resp.get("users", [])
        _add(report, lang, "diag_item_pipe", STATUS_OK,
             t("diag_pipe_ok", lang, users=", ".join(users) if users else t("diag_none", lang)))
    else:
        _add(report, lang, "diag_item_pipe", STATUS_FAIL, t("diag_pipe_bad_response", lang, resp=resp))


def _check_cp(report: DiagnosticReport, lang: str) -> None:
    dll_exists = config.CP_DLL.exists()
    try:
        import winreg

        cp_key = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\{_CP_CLSID}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, cp_key):
            cp_registered = True
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{_CP_CLSID}\InprocServer32") as key:
            inproc, _ = winreg.QueryValueEx(key, None)
    except Exception as exc:
        detail = t("diag_cp_detail", lang, dll=config.CP_DLL, exists=_yes_no(dll_exists, lang),
                   registered=_yes_no(False, lang), inproc=t("diag_unavailable", lang, e=exc))
        _add(report, lang, "diag_item_cp", STATUS_FAIL, detail, "diag_advice_register_cp")
        return

    inproc_exists = Path(inproc).exists()
    ok = dll_exists and cp_registered and inproc_exists
    detail = t("diag_cp_detail", lang, dll=config.CP_DLL, exists=_yes_no(dll_exists, lang),
               registered=_yes_no(cp_registered, lang), inproc=inproc)
    _add(report, lang, "diag_item_cp", STATUS_OK if ok else STATUS_FAIL, detail,
         "" if ok else "diag_advice_register_cp")


def _check_models(report: DiagnosticReport, lang: str) -> None:
    items = [
        (t("diag_model_det", lang), config.MODELS_DIR / "buffalo_l" / "det_10g.onnx"),
        (t("diag_model_rec", lang), config.MODELS_DIR / "buffalo_l" / "w600k_r50.onnx"),
        (t("diag_model_liveness", lang), config.FACE_LANDMARKER),
    ]
    missing = [name for name, path in items if not path.exists()]
    if missing:
        _add(report, lang, "diag_item_models", STATUS_FAIL,
             t("diag_models_missing", lang, names=", ".join(missing)), "diag_advice_offline_check")
        return

    t0 = time.perf_counter()
    try:
        import threading

        import numpy as np

        from .detector import FaceDetector
        from .liveness import FaceMeshTracker

        FaceDetector().load()
        tracker = FaceMeshTracker()
        tracker.process(np.zeros((480, 640, 3), dtype=np.uint8))
        threading.Thread(target=tracker.close, daemon=True).start()
    except Exception as exc:
        _add(report, lang, "diag_item_models", STATUS_FAIL, t("diag_models_load_fail", lang, e=exc))
        return

    try:
        from .antispoof import get_antispoof

        antispoof_ready = get_antispoof() is not None
    except Exception:
        antispoof_ready = False
    status = STATUS_OK if antispoof_ready else STATUS_WARN
    _add(
        report, lang, "diag_item_models", status,
        t("diag_models_ok", lang, seconds=f"{time.perf_counter() - t0:.1f}",
          antispoof=_yes_no(antispoof_ready, lang)),
        "" if antispoof_ready else "diag_advice_antispoof_optional",
    )


def _check_camera(report: DiagnosticReport, lang: str) -> None:
    try:
        idx = int(FaceStore().load().get_settings().get("camera_index", 0))
    except Exception:
        idx = 0
    try:
        from .camera import Camera

        cam = Camera(idx)
        try:
            cam.open(timeout_s=8.0)
            frame = cam.read()
        finally:
            cam.release()
    except Exception as exc:
        _add(report, lang, "diag_item_camera", STATUS_FAIL,
             t("diag_camera_fail", lang, idx=idx, e=exc), "diag_advice_camera_index")
        return
    h, w = frame.shape[:2]
    _add(report, lang, "diag_item_camera", STATUS_OK,
         t("diag_camera_ok", lang, idx=idx, w=w, h=h))


def _check_log(report: DiagnosticReport, lang: str) -> None:
    path = config.DATA_DIR / "service.log"
    if not path.exists():
        _add(report, lang, "diag_item_log", STATUS_WARN, t("diag_log_missing", lang, path=path))
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        _add(report, lang, "diag_item_log", STATUS_WARN, t("diag_log_read_fail", lang, e=exc))
        return
    warn_count = sum("WARNING" in line or "WARN" in line for line in lines)
    error_count = sum("ERROR" in line or "Traceback" in line for line in lines)
    mtime = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    tail = "\n".join(lines[-_MAX_LOG_LINES:]) if lines else t("diag_log_empty_tail", lang)
    status = STATUS_FAIL if error_count else STATUS_WARN if warn_count else STATUS_OK
    _add(
        report, lang, "diag_item_log", status,
        t("diag_log_detail", lang, path=path, mtime=mtime, warnings=warn_count,
          errors=error_count, tail=tail),
    )
