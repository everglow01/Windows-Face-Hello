from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from face_hello import platform_backend
from face_hello.camera import Camera, camera_source, describe_source


def test_camera_source_prefers_url_over_index():
    assert camera_source({"camera_index": 2}) == 2
    assert camera_source({"camera_index": 2, "camera_url": "  "}) == 2
    assert camera_source({"camera_index": 2, "camera_url": " http://h:8080/video "}) == (
        "http://h:8080/video"
    )


def test_camera_source_percent_encodes_separate_credentials():
    settings = {
        "camera_url": "http://10.0.0.5:8080/video",
        "camera_url_username": "me@home",
        "camera_url_password": "p@ss:w/rd#1",
    }
    assert camera_source(settings) == "http://me%40home:p%40ss%3Aw%2Frd%231@10.0.0.5:8080/video"
    assert camera_source({**settings, "camera_url_password": ""}) == (
        "http://me%40home@10.0.0.5:8080/video"
    )


def test_camera_source_keeps_credentials_already_in_url():
    settings = {
        "camera_url": "http://old:secret@10.0.0.5:8080/video",
        "camera_url_username": "new",
        "camera_url_password": "other",
    }
    assert camera_source(settings) == "http://old:secret@10.0.0.5:8080/video"
    assert camera_source({"camera_url": "http://h/video", "camera_url_password": "x"}) == (
        "http://h/video"
    )


def test_describe_source_masks_stream_credentials():
    assert describe_source(1) == "index=1"
    assert describe_source("http://user:secret@10.0.0.5:8080/video") == (
        "url=http://***@10.0.0.5:8080/video"
    )
    assert describe_source("rtsp://10.0.0.5/live") == "url=rtsp://10.0.0.5/live"
    # 未编码的 @ 出现在密码里时也要整段遮蔽,不能只遮到第一个 @
    assert describe_source("http://u:p@ss@10.0.0.5/video") == "url=http://***@10.0.0.5/video"


class _StreamCapture:
    """模拟网络串流:每次 read 回下一帧(帧值=序号),读到 limit 之后阻塞直到 release。"""

    def __init__(self, limit: int):
        self.limit = limit
        self.count = 0
        self.released = False
        self.more = threading.Event()

    def isOpened(self):
        return True

    def read(self):
        if self.count >= self.limit:
            self.more.wait(timeout=2)
            return False, None
        self.count += 1
        return True, np.full((2, 2, 3), self.count, dtype=np.uint8)

    def release(self):
        self.released = True


def test_stream_read_returns_latest_frame_and_drops_backlog(monkeypatch):
    cap = _StreamCapture(limit=5)
    monkeypatch.setattr(platform_backend, "open_capture", lambda _src: cap)
    cam = Camera("http://h/video")
    cam.open(timeout_s=1)
    try:
        # 等读线程把 2..5 帧读完;消费者只拿到最新一帧,积压的旧帧被丢弃
        deadline = time.monotonic() + 2
        while cam._reader._seq < 5 and time.monotonic() < deadline:
            time.sleep(0.01)
        frame = cam.read()
        assert int(frame[0, 0, 0]) == 5
        cap.more.set()  # 串流结束
        with pytest.raises(RuntimeError):
            cam.read()
    finally:
        cam.release()
    assert cap.released is True


def test_stream_open_failure_message_hides_credentials(monkeypatch):
    class _Dead:
        def isOpened(self):
            return False

        def release(self):
            pass

    monkeypatch.setattr(platform_backend, "open_capture", lambda _src: _Dead())
    times = iter((0.0, 0.0, 0.0, 1.0))
    monkeypatch.setattr("face_hello.camera.time.monotonic", lambda: next(times))
    cam = Camera("http://user:secret@10.0.0.5:8080/video")
    with pytest.raises(RuntimeError) as exc:
        cam.open(timeout_s=0.5)
    assert "secret" not in str(exc.value)
    assert "***@10.0.0.5" in str(exc.value)
