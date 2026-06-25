"""FaceMeshTracker 复用契约:注入的 tracker(服务长寿命共享实例)不在会话结束时被关,
各会话自建的才关;_AuthRunner._run 把 self.tracker 透传给 authenticate_blocking。

全程不碰真 MediaPipe/摄像头:活体开启但注入 fake tracker,_finish 直接调,不跑活体循环。
"""
from __future__ import annotations

import time

from conftest import FakeDetector, make_store, unit_vec

from face_hello.auth import AuthResult, AuthSession
from face_hello.service import _AuthRunner


class _FakeTracker:
    """FaceMeshTracker 的最小替身:process 返回 None,close 置标志。"""

    def __init__(self) -> None:
        self.closed = False

    def process(self, frame_bgr):
        return None

    def close(self) -> None:
        self.closed = True


def test_injected_tracker_not_closed(tmp_path):
    # 注入的 tracker 由持有者(服务)负责生命周期,会话结束绝不关它
    store = make_store(tmp_path, liveness_enabled=True)
    fake = _FakeTracker()
    s = AuthSession(FakeDetector(), store, tracker=fake)
    assert s._owns_tracker is False
    assert s._tracker is fake
    s._finish(AuthResult(False, "done", biometric=True))
    assert fake.closed is False


def test_owned_tracker_closed(tmp_path, monkeypatch):
    # 不传 tracker → 自建 → 会话结束在后台守护线程关掉
    created = []

    def _make():
        t = _FakeTracker()
        created.append(t)
        return t

    monkeypatch.setattr("face_hello.auth.FaceMeshTracker", lambda: _make())
    store = make_store(tmp_path, liveness_enabled=True)
    s = AuthSession(FakeDetector(), store)
    assert s._owns_tracker is True
    assert len(created) == 1
    s._finish(AuthResult(False, "done", biometric=True))
    # close 丢守护线程,稍等其完成
    deadline = time.monotonic() + 5
    while not created[0].closed and time.monotonic() < deadline:
        time.sleep(0.01)
    assert created[0].closed is True


def test_runner_injects_shared_tracker(tmp_path, monkeypatch):
    # _run 把 runner 持有的长寿命 tracker 透传给 authenticate_blocking
    captured = {}

    def fake_auth(detector, store, **kwargs):
        captured["tracker"] = kwargs.get("tracker")
        return AuthResult(False, "x", biometric=True)

    monkeypatch.setattr("face_hello.service.authenticate_blocking", fake_auth)
    store = make_store(tmp_path)
    store.add_profile("alice", unit_vec(1, 0))  # 非空,_run 才真去认证
    sentinel = object()
    r = _AuthRunner()
    r.tracker = sentinel
    r._run(None, store)
    assert captured["tracker"] is sentinel
