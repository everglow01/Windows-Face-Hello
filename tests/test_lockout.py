"""_AuthRunner 失败锁定状态机:只对真生物特征拒绝计数,基础设施错误不锁死用户。

monkeypatch 掉 authenticate_blocking(避免开摄像头),用未落盘的内存 store(load() 对
缺失文件 no-op,不触 DPAPI)。计数逻辑直接同步调 _run,绕开线程不 flaky;锁定到期的
放行路径才用 start() 起线程并 join 验证。
"""
from __future__ import annotations

import time

from conftest import make_store, unit_vec

from face_hello.auth import AuthResult
from face_hello.service import _AuthRunner


def _bio_fail() -> AuthResult:
    return AuthResult(False, "x", biometric=True)


def _store(tmp_path, **settings):
    s = make_store(tmp_path, **settings)
    s.add_profile("alice", unit_vec(1, 0))  # 非空,_run 才会真去认证
    return s


def test_lock_after_max_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("face_hello.service.authenticate_blocking", lambda *a, **k: _bio_fail())
    store = _store(tmp_path, lockout_max_fails=3, lockout_seconds=30)
    r = _AuthRunner()
    r._run(None, store)
    r._run(None, store)
    assert r._fails == 2
    assert r._locked_until == 0.0  # 还没锁
    r._run(None, store)            # 第 3 次达阈值
    assert r._fails == 0           # 锁定时清零
    assert r._locked_until > time.monotonic()


def test_success_resets_fail_count(tmp_path, monkeypatch):
    results = [_bio_fail(), _bio_fail(), AuthResult(True, "ok", "alice", 0.9, biometric=True)]
    monkeypatch.setattr("face_hello.service.authenticate_blocking", lambda *a, **k: results.pop(0))
    store = _store(tmp_path, lockout_max_fails=5, lockout_seconds=30)
    r = _AuthRunner()
    r._run(None, store)
    r._run(None, store)
    assert r._fails == 2
    r._run(None, store)            # 成功
    assert r._fails == 0
    assert r._locked_until == 0.0


def test_infra_error_not_counted(tmp_path, monkeypatch):
    # biometric=False(如未录入 / 摄像头不可用 / 异常)不计入锁定——红线:不锁死用户
    monkeypatch.setattr(
        "face_hello.service.authenticate_blocking",
        lambda *a, **k: AuthResult(False, "camera fail", biometric=False),
    )
    store = _store(tmp_path, lockout_max_fails=3, lockout_seconds=30)
    r = _AuthRunner()
    for _ in range(5):
        r._run(None, store)
    assert r._fails == 0
    assert r._locked_until == 0.0


def test_max_fails_zero_disables_lockout(tmp_path, monkeypatch):
    monkeypatch.setattr("face_hello.service.authenticate_blocking", lambda *a, **k: _bio_fail())
    store = _store(tmp_path, lockout_max_fails=0, lockout_seconds=30)
    r = _AuthRunner()
    for _ in range(10):
        r._run(None, store)
    assert r._fails == 0
    assert r._locked_until == 0.0


def test_start_rejects_while_locked(tmp_path, monkeypatch):
    # 锁定窗口内 start() 直接回锁定结果,绝不开摄像头
    def boom(*a, **k):
        raise AssertionError("locked 时不应调用 authenticate_blocking")

    monkeypatch.setattr("face_hello.service.authenticate_blocking", boom)
    store = _store(tmp_path, lockout_max_fails=3, lockout_seconds=30, language="zh")
    r = _AuthRunner()
    r._locked_until = time.monotonic() + 30
    r.start(None, store)
    assert r._done is True
    assert r._result is not None and r._result.success is False
    assert "已锁定" in r._instruction
    assert r._thread is None  # 没起认证线程


def test_start_runs_after_lock_expires(tmp_path, monkeypatch):
    ran = {"n": 0}

    def fake_auth(*a, **k):
        ran["n"] += 1
        return _bio_fail()

    monkeypatch.setattr("face_hello.service.authenticate_blocking", fake_auth)
    store = _store(tmp_path, lockout_max_fails=3, lockout_seconds=30, language="zh")
    r = _AuthRunner()
    r._locked_until = time.monotonic() - 1  # 已过期
    r.start(None, store)
    assert r._thread is not None
    r._thread.join(timeout=5)
    assert ran["n"] == 1  # 放行,真的去认证了
