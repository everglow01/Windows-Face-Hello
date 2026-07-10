from __future__ import annotations

import numpy as np
import pytest

from face_hello import platform_backend
from face_hello.camera import Camera


class _Capture:
    def isOpened(self):
        return True

    def read(self):
        return True, np.zeros((8, 8, 3), dtype=np.uint8)

    def release(self):
        pass


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
