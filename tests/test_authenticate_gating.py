"""同步 authenticate 命令门控契约:它绕过失败锁定,故仅开发态可用,安装态(生产)禁用。

全程不碰摄像头/真模型:monkeypatch config.IS_INSTALLED 与 authenticate_blocking。
_handle 在运行时读 config.IS_INSTALLED,故 patch 模块属性即可切换两态。
"""
from __future__ import annotations

from conftest import FakeDetector, make_store, unit_vec

from face_hello.auth import AuthResult
from face_hello.service import _handle


def test_authenticate_disabled_when_installed(tmp_path, monkeypatch):
    # 安装态:authenticate 直接拒,且绝不调用 authenticate_blocking(开摄像头)
    monkeypatch.setattr("face_hello.service.config.IS_INSTALLED", True)

    def boom(*a, **k):
        raise AssertionError("生产态不应调用 authenticate_blocking")

    monkeypatch.setattr("face_hello.service.authenticate_blocking", boom)
    store = make_store(tmp_path)
    store.add_profile("alice", unit_vec(1, 0))  # 即便有人脸库也照样拒
    resp = _handle({"cmd": "authenticate"}, FakeDetector(), store)
    assert resp["ok"] is False
    assert "disabled" in resp["reason"]


def test_authenticate_allowed_in_dev(tmp_path, monkeypatch):
    # 开发态:authenticate 正常走认证
    monkeypatch.setattr("face_hello.service.config.IS_INSTALLED", False)
    monkeypatch.setattr(
        "face_hello.service.authenticate_blocking",
        lambda *a, **k: AuthResult(True, "ok", name="alice", similarity=0.7, biometric=True),
    )
    store = make_store(tmp_path)
    store.add_profile("alice", unit_vec(1, 0))
    resp = _handle({"cmd": "authenticate"}, FakeDetector(), store)
    assert resp["ok"] is True
    assert resp["user"] == "alice"


def test_ping_still_works_when_installed(tmp_path, monkeypatch):
    # 门控只收 authenticate:ping 在安装态照常应答(证明没误伤整条管道)
    monkeypatch.setattr("face_hello.service.config.IS_INSTALLED", True)
    store = make_store(tmp_path)
    store.add_profile("alice", unit_vec(1, 0))
    store.add_profile("alice", unit_vec(0, 1), replace=False)
    store.add_profile("bob", unit_vec(0, 0, 1), replace=False)
    resp = _handle({"cmd": "ping"}, FakeDetector(), store)
    assert resp["ok"] is True
    assert resp["ready"] is True
    assert resp["users"] == ["alice", "bob"]
