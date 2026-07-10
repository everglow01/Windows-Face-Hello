from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import config
from .store import FaceStore


@dataclass(frozen=True)
class ServiceInfo:
    status: int
    start_type: int
    account: str
    image_path: str


class PipeConnectError(RuntimeError):
    def __init__(self, cause: Exception):
        super().__init__(str(cause))
        self.winerror = getattr(cause, "winerror", None)


_SERVICE_STATE_KEYS = {
    1: "svc_stopped",
    2: "svc_starting",
    3: "svc_stopping",
    4: "svc_running",
    7: "svc_paused",
}


def service_state_key(status: int) -> str | None:
    return _SERVICE_STATE_KEYS.get(status)


def required_model_paths() -> list[tuple[str, Path]]:
    return [
        ("detector", config.INSIGHTFACE_DETECTION_MODEL),
        ("recognition", config.INSIGHTFACE_RECOGNITION_MODEL),
        ("liveness", config.FACE_LANDMARKER),
    ]


def load_models() -> tuple[float, bool]:
    import numpy as np

    from .antispoof import get_antispoof
    from .detector import FaceDetector
    from .liveness import FaceMeshTracker

    started = time.perf_counter()
    FaceDetector().load()
    tracker = FaceMeshTracker()
    tracker.process(np.zeros((480, 640, 3), dtype=np.uint8))
    threading.Thread(target=tracker.close, daemon=True).start()
    return time.perf_counter() - started, get_antispoof() is not None


def configured_camera_index() -> int:
    try:
        return int(FaceStore().load().get_settings().get("camera_index", 0))
    except Exception:
        return 0


def capture_camera_frame(index: int, timeout_s: float = 8.0):
    from .camera import Camera

    cam = Camera(index)
    try:
        cam.open(timeout_s=timeout_s)
        return cam.read()
    finally:
        cam.release()


def call_pipe(request: dict) -> dict:
    import win32file
    import win32pipe

    try:
        handle = win32file.CreateFile(
            config.PIPE_NAME,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0, None, win32file.OPEN_EXISTING, 0, None,
        )
    except Exception as exc:
        raise PipeConnectError(exc) from exc
    try:
        win32pipe.SetNamedPipeHandleState(handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)
        win32file.WriteFile(handle, json.dumps(request).encode("utf-8"))
        return json.loads(win32file.ReadFile(handle, 65536)[1].decode("utf-8"))
    finally:
        win32file.CloseHandle(handle)


def query_service() -> ServiceInfo:
    import win32con
    import win32service
    import win32serviceutil

    status = win32serviceutil.QueryServiceStatus(config.SERVICE_NAME)[1]
    scm = None
    svc = None
    try:
        scm = win32service.OpenSCManager(None, None, win32con.GENERIC_READ)
        svc = win32service.OpenService(scm, config.SERVICE_NAME, win32service.SERVICE_QUERY_CONFIG)
        cfg = win32service.QueryServiceConfig(svc)
    finally:
        if svc is not None:
            win32service.CloseServiceHandle(svc)
        if scm is not None:
            win32service.CloseServiceHandle(scm)
    return ServiceInfo(status, cfg[1], cfg[7], cfg[3])
