from __future__ import annotations

import threading
import time
import zipfile
from datetime import datetime

import numpy as np
import pytest

from face_hello import diagnostics, platform_backend, probes
from face_hello.camera import (
    Camera,
    CameraSourceError,
    camera_source,
    describe_source,
    mask_url,
)


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


def test_describe_source_masks_query_tokens_and_fragment():
    assert describe_source("http://10.0.0.5:8080/video?token=abc123&apiKey=k9&fps=30") == (
        "url=http://10.0.0.5:8080/video?token=***&apiKey=***&fps=***"
    )
    assert describe_source("rtsp://10.0.0.5/live?SECRETVALUE#frag") == (
        "url=rtsp://10.0.0.5/live?***#***"
    )
    # 格式错误的 URL 也能安全显示,不抛错
    assert "secret" not in mask_url("http://[broken:secret@host／x/video?token=secret")
    assert mask_url("") == ""


@pytest.mark.parametrize("url", [
    "http://host／x:8080/video",   # 主机名误含全角斜杠:urlsplit 的错误信息会带出 netloc
    "http://[broken/video",             # 未闭合的 IPv6:urlsplit 抛错
    "http://10.0.0.5:99999/video",      # 端口越界:.port 抛错
    "http://10.0.0.5:0/video",
    "file:///C:/Windows/win.ini",       # 非网络协议
    "ftp://10.0.0.5/video",
    "10.0.0.5:8080/video",              # 漏写 scheme
    "http:///video",                    # 没有主机名
])
def test_camera_source_rejects_malformed_url_without_leaking_it(url):
    settings = {"camera_url": url, "camera_url_username": "me",
                "camera_url_password": "hunter2-secret", "camera_index": 0}
    with pytest.raises(CameraSourceError) as exc:
        camera_source(settings)
    message = str(exc.value)
    assert "hunter2" not in message and "10.0.0.5" not in message and "host" not in message
    # 不留异常链:logging.exception 会把 __context__ 里的原始 ValueError(含 URL)一起打出来
    assert exc.value.__cause__ is None and exc.value.__context__ is None
    # 不填独立帐号时同样要校验,不能原样交给 FFmpeg
    with pytest.raises(CameraSourceError):
        camera_source({"camera_url": url})


def test_camera_source_accepts_supported_stream_schemes():
    for url in ("https://h/video", "rtsp://10.0.0.5:554/live", "RTSPS://h/x", "rtmp://h/app",
                "http://[::1]:8080/video"):
        assert camera_source({"camera_url": url}) == url


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


def test_stream_read_fails_fast_after_disconnect_even_with_unconsumed_frame(monkeypatch):
    cap = _StreamCapture(limit=3)
    monkeypatch.setattr(platform_backend, "open_capture", lambda _src: cap)
    cam = Camera("http://h/video")
    cam.open(timeout_s=1)
    try:
        deadline = time.monotonic() + 2
        while cam._reader._seq < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        cap.more.set()  # 断流:读线程标记 _error,但第 3 帧还没被取走
        deadline = time.monotonic() + 2
        while not cam._reader._error and time.monotonic() < deadline:
            time.sleep(0.01)
        assert cam._reader._seq > cam._reader._consumed  # 确有未提交的缓存帧
        with pytest.raises(RuntimeError, match="中断"):
            cam.read()
    finally:
        cam.release()


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


def _patch_store_settings(monkeypatch, settings: dict) -> None:
    class _Store:
        def load(self):
            return self

        def get_settings(self):
            return settings

    monkeypatch.setattr(probes, "FaceStore", _Store)


def test_configured_camera_reports_invalid_url_instead_of_falling_back(monkeypatch):
    _patch_store_settings(monkeypatch, {"camera_url": "http://[broken/video", "camera_index": 0})
    with pytest.raises(CameraSourceError):
        probes.configured_camera_index()


def test_configured_camera_without_url_uses_index(monkeypatch):
    _patch_store_settings(monkeypatch, {"camera_url": "", "camera_index": 2})
    assert probes.configured_camera_index() == 2


def test_camera_diagnostic_fails_on_invalid_url_without_testing_usb(monkeypatch):
    _patch_store_settings(monkeypatch, {"camera_url": "http://[broken:pw@x/video",
                                        "camera_url_username": "me", "camera_index": 0})
    captured = []
    monkeypatch.setattr(probes, "capture_camera_frame", lambda src, **_kw: captured.append(src))
    report = diagnostics.DiagnosticReport(datetime(2026, 10, 8), "development", "me", False)
    diagnostics._check_camera(report, "en")
    assert captured == []  # 没有静默改测 USB 摄像头 0
    assert report.items[0].status == diagnostics.STATUS_FAIL
    assert "pw" not in report.items[0].detail


def test_export_bundle_redacts_stream_url_credentials(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "service.log").write_text(
        "ERROR open failed http://cam:hunter2@10.0.0.5:8080/video?token=tok-123&apiKey=key-456\n"
        "WARNING raw rtsp://10.0.0.5/live?sig=sig-789#frag-000 api_key=key-999\n"
        "ERROR http://cam/video?token=prefix@query-tail\n"
        "ERROR rtsp://cam/live#prefix@frag-tail\n"
        "ERROR password=prefix&password-tail\n",
        encoding="utf-8",
    )
    report = diagnostics.DiagnosticReport(datetime(2026, 10, 8), "development", "me", False)
    report.items.append(diagnostics.DiagnosticItem(
        "Camera", diagnostics.STATUS_FAIL,
        "Camera url=http://***@10.0.0.5/video?access_token=tok-abc is unavailable",
    ))
    target = diagnostics.export_diagnostic_bundle(tmp_path / "bundle", report, "en", data)
    with zipfile.ZipFile(target) as archive:
        combined = "\n".join(archive.read(n).decode("utf-8") for n in archive.namelist())
    for secret in ("hunter2", "tok-123", "key-456", "sig-789", "frag-000", "key-999", "tok-abc",
                   "query-tail", "frag-tail", "password-tail"):
        assert secret not in combined
    assert "10.0.0.5:8080/video" in combined  # 主机与路径仍保留,便于排错


@pytest.mark.parametrize(("url", "masked"), [
    ("http://cam/video?token=prefix@QUERY_TAIL", "http://cam/video?token=***"),
    ("http://user:secret@cam/video?token=prefix@COMBINED_TAIL",
     "http://***@cam/video?token=***"),
    ("rtsp://cam/live#prefix@FRAGMENT_TAIL", "rtsp://cam/live#***"),
    ("http://cam/video?token=prefix@QUERY_TAIL#prefix@FRAGMENT_TAIL",
     "http://cam/video?token=***#***"),
])
def test_mask_url_keeps_query_and_fragment_out_of_userinfo(url, masked):
    assert mask_url(url) == masked
    assert describe_source(url) == "url=" + masked


@pytest.mark.parametrize("key", ["password", "token", "api_key"])
def test_redact_assignment_includes_ampersand(key):
    assert diagnostics.redact_diagnostics_text(f"{key}=prefix&SECRET_TAIL", []) == (
        f"{key}=<redacted>"
    )
