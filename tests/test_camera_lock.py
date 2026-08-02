from __future__ import annotations

import numpy as np
import pytest

from face_hello import platform_backend
from face_hello.camera import Camera


class _Capture:
    def __init__(self, opened=True, read_ok=True):
        self.opened = opened
        self.read_ok = read_ok
        self.released = False

    def isOpened(self):
        return self.opened

    def read(self):
        if not self.read_ok:
            return False, None
        return True, np.zeros((8, 8, 3), dtype=np.uint8)

    def release(self):
        self.released = True


def test_camera_is_exclusive_within_process(monkeypatch):
    monkeypatch.setattr(platform_backend, "open_capture", lambda _index: _Capture())
    first = Camera(0)
    second = Camera(1)
    first.open()
    try:
        with pytest.raises(RuntimeError, match="另一个 FaceHello 操作"):
            second.open()
    finally:
        first.release()
    second.open()
    second.release()


def test_camera_retries_until_device_recovers(monkeypatch):
    unopened = _Capture(opened=False)
    unreadable = _Capture(read_ok=False)
    ready = _Capture()
    captures = [unopened, unreadable, ready]
    monkeypatch.setattr(
        platform_backend, "open_capture", lambda _index: captures.pop(0)
    )
    monkeypatch.setattr("face_hello.camera.time.sleep", lambda _delay: None)

    camera = Camera(0)
    camera.open(timeout_s=1)
    assert unopened.released is True
    assert unreadable.released is True
    camera.release()
    assert ready.released is True


def test_camera_timeout_releases_lock_for_next_open(monkeypatch):
    failed = _Capture(opened=False)
    ready = _Capture()
    captures = [failed, ready]
    monkeypatch.setattr(
        platform_backend, "open_capture", lambda _index: captures.pop(0)
    )
    times = iter((0.0, 0.0, 0.0, 1.0))
    monkeypatch.setattr("face_hello.camera.time.monotonic", lambda: next(times))

    first = Camera(0)
    with pytest.raises(RuntimeError, match="无法打开摄像头"):
        first.open(timeout_s=0.5)
    assert failed.released is True

    monkeypatch.setattr("face_hello.camera.time.monotonic", lambda: 1.0)
    second = Camera(0)
    second.open()
    second.release()
