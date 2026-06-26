"""AuthSession._recognize 的判定门:没脸 / 匹配 / 不匹配 / 歧义 / 反欺骗 / fail-open。

把 liveness_enabled 关掉,构造期就不建 FaceMeshTracker、不触 MediaPipe,session 直接
进 recognize 阶段;detector 用 fake,反欺骗用 monkeypatch 注入,全程无摄像头/真模型。
"""
from __future__ import annotations

import numpy as np
import pytest

from conftest import FakeDetector, FakeFace, make_store, unit_vec

from face_hello.auth import AuthSession
from face_hello.i18n import t

FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


def _session(tmp_path, detector, profiles, **settings):
    """建一个关了活体的 AuthSession;profiles = [(name, embedding), ...]。"""
    settings.setdefault("liveness_enabled", False)
    store = make_store(tmp_path, **settings)
    for name, emb in profiles:
        store.add_profile(name, emb)
    return AuthSession(detector, store)


class _FakeAntispoof:
    def __init__(self, value):
        self._value = value

    def score(self, frame_bgr):
        if isinstance(self._value, Exception):
            raise self._value
        return self._value


class _SeqAntispoof:
    """按调用次序返回 values 里的值(用尽后返回 None),模拟逐帧的检测结果序列。"""

    def __init__(self, values):
        self._values = list(values)

    def score(self, frame_bgr):
        return self._values.pop(0) if self._values else None


def _patch_antispoof(monkeypatch, model):
    monkeypatch.setattr("face_hello.antispoof.get_antispoof", lambda: model)


def test_no_face_rejected_biometric(tmp_path):
    det = FakeDetector(face=None)
    s = _session(tmp_path, det, [("alice", unit_vec(1, 0))], antispoof_enabled=False)
    s.feed(FRAME)
    assert s.done and s.result.success is False
    assert s.result.biometric is True
    assert s.result.reason == t("no_face", "zh")


def test_match_success(tmp_path):
    probe = unit_vec(1, 0)
    det = FakeDetector(face=FakeFace(embedding=probe))
    s = _session(tmp_path, det, [("alice", unit_vec(1, 0))], antispoof_enabled=False)
    s.feed(FRAME)
    assert s.result.success is True
    assert s.result.name == "alice"
    assert s.result.biometric is True


def test_below_threshold_mismatch(tmp_path):
    # probe 与 alice 正交 → 相似度 0 < 阈值
    det = FakeDetector(face=FakeFace(embedding=unit_vec(0, 1)))
    s = _session(tmp_path, det, [("alice", unit_vec(1, 0))], antispoof_enabled=False)
    s.feed(FRAME)
    assert s.result.success is False
    assert s.result.biometric is True
    assert s.result.reason.startswith(t("face_mismatch", "zh", sim=0.0, thr=0.40)[:6])


def test_ambiguous_rejected(tmp_path):
    # bob 贴近 alice,margin < 默认 match_margin(0.05)→ 歧义拒绝(防把 A 解成 B)
    det = FakeDetector(face=FakeFace(embedding=unit_vec(1, 0)))
    s = _session(
        tmp_path, det,
        [("alice", unit_vec(1, 0)), ("bob", unit_vec(0.98, 0.2))],
        antispoof_enabled=False,
    )
    s.feed(FRAME)
    assert s.result.success is False
    assert s.result.biometric is True
    assert s.result.name is None
    # 走的是歧义分支(margin = best - 次相似者),而非普通不匹配
    margin = s.result.similarity - _cos_bob()
    assert s.result.reason == t("ambiguous_match", "zh", margin=margin, m=0.05)


def _cos_bob():
    from face_hello.matcher import cosine_similarity
    return cosine_similarity(unit_vec(1, 0), unit_vec(0.98, 0.2))


def test_spoof_rejected_before_match(tmp_path, monkeypatch):
    # 反欺骗判假体 → 在比对之前就拒掉(best_match 不应被调用)
    calls = {"n": 0}
    real_bm = __import__("face_hello.matcher", fromlist=["best_match_with_margin"]).best_match_with_margin

    def spy(*a, **k):
        calls["n"] += 1
        return real_bm(*a, **k)

    monkeypatch.setattr("face_hello.auth.best_match_with_margin", spy)
    _patch_antispoof(monkeypatch, _FakeAntispoof(0.04))  # < 0.55
    det = FakeDetector(face=FakeFace(embedding=unit_vec(1, 0)))
    s = _session(tmp_path, det, [("alice", unit_vec(1, 0))])  # 反欺骗默认开
    s.feed(FRAME)
    assert s.result.success is False
    assert s.result.biometric is True
    assert s.result.reason == t("spoof_detected", "zh", p=0.04)
    assert calls["n"] == 0  # 假体根本没进入身份匹配


def test_antispoof_missing_fail_open(tmp_path, monkeypatch):
    # 模型不可用(get_antispoof 返回 None)→ fail-open,照常比对解锁(红线:缺模型不锁死)
    _patch_antispoof(monkeypatch, None)
    det = FakeDetector(face=FakeFace(embedding=unit_vec(1, 0)))
    s = _session(tmp_path, det, [("alice", unit_vec(1, 0))])
    s.feed(FRAME)
    assert s.result.success is True
    assert s.result.name == "alice"


def test_antispoof_exception_fail_open(tmp_path, monkeypatch):
    # 推理抛异常 → fail-open,照常比对
    _patch_antispoof(monkeypatch, _FakeAntispoof(RuntimeError("boom")))
    det = FakeDetector(face=FakeFace(embedding=unit_vec(1, 0)))
    s = _session(tmp_path, det, [("alice", unit_vec(1, 0))])
    s.feed(FRAME)
    assert s.result.success is True
    assert s.result.name == "alice"


def test_antispoof_pass_then_match(tmp_path, monkeypatch):
    # 反欺骗判真(score ≥ 阈值)→ 继续比对通过
    _patch_antispoof(monkeypatch, _FakeAntispoof(0.9))
    det = FakeDetector(face=FakeFace(embedding=unit_vec(1, 0)))
    s = _session(tmp_path, det, [("alice", unit_vec(1, 0))])
    s.feed(FRAME)
    assert s.result.success is True
    assert s.result.name == "alice"


def test_antispoof_single_miss_not_fail_open(tmp_path, monkeypatch):
    # #4 加固:某帧没检到脸(None)不立刻 fail-open——继续采样,后续帧判假 → 拒。
    # 堵住「回放视频在识别那帧恰好躲过 RetinaFace 就溜进识别」的空子。
    _patch_antispoof(monkeypatch, _SeqAntispoof([None, 0.04]))
    det = FakeDetector(face=FakeFace(embedding=unit_vec(1, 0)))
    s = _session(tmp_path, det, [("alice", unit_vec(1, 0))])
    s.feed(FRAME)
    assert s.done is False  # 第一帧 None:尚无定论,既不放行也不解锁
    s.feed(FRAME)
    assert s.done and s.result.success is False
    assert s.result.reason == t("spoof_detected", "zh", p=0.04)


def test_antispoof_all_miss_fail_open_after_cap(tmp_path, monkeypatch):
    # 连续没检到脸达上限 → fail-open 照常解锁(红线:不锁死用户),但要采满 N 帧而非单帧即放
    _patch_antispoof(monkeypatch, _SeqAntispoof([None, None, None]))
    det = FakeDetector(face=FakeFace(embedding=unit_vec(1, 0)))
    s = _session(tmp_path, det, [("alice", unit_vec(1, 0))], antispoof_max_frames=3)
    s.feed(FRAME)
    assert s.done is False  # 第 1 帧
    s.feed(FRAME)
    assert s.done is False  # 第 2 帧,仍未达上限
    s.feed(FRAME)          # 第 3 帧达上限 → fail-open → 比对解锁
    assert s.done and s.result.success is True
    assert s.result.name == "alice"
