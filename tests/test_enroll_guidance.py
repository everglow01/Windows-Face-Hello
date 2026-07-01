"""Enroller.evaluate 录入质量引导:亮度 / 距离 / 居中 / 清晰度 / 分模式姿态门。

纯逻辑、无摄像头 / 真模型:用合成的 np 帧(均匀填充 → ROI 亮度=填充值)+ 可控 FakeFace
(bbox 定面积 / 居中、kps 定 yaw)。**只覆盖控制台录入路径的判定,解锁路径不涉及。**
"""
from __future__ import annotations

import numpy as np

from conftest import FakeDetector, FakeFace, unit_vec

from face_hello.enroll import Enroller

_W, _H = 640, 480


def _frame(fill: int) -> np.ndarray:
    """均匀填充帧:人脸 ROI 灰度均值即 fill。"""
    return np.full((_H, _W, 3), fill, dtype=np.uint8)


def _kps(yaw: float) -> np.ndarray:
    """双眼固定(眼距 20),鼻尖按 yaw 横移:nose_x = 眼中点 + yaw*眼距 → _yaw_ratio==yaw。"""
    return np.array(
        [[40, 50], [60, 50], [50 + yaw * 20, 56], [44, 70], [56, 70]], dtype=np.float32
    )


def _face(frac: float = 0.10, cx: float = 0.5, cy: float = 0.5,
          det_score: float = 0.9, yaw: float = 0.0) -> FakeFace:
    """按面积占比 frac、画面相对中心 (cx,cy) 造一个居中可控的 bbox。"""
    side = (frac * _W * _H) ** 0.5
    half = side / 2.0
    px, py = cx * _W, cy * _H
    bbox = (px - half, py - half, px + half, py + half)
    return FakeFace(unit_vec(1), bbox=bbox, det_score=det_score, kps=_kps(yaw))


def _enr() -> Enroller:
    return Enroller(FakeDetector(), target_samples=5)  # evaluate 不依赖 detector/target


def test_ok_base_frontal():
    assert _enr().evaluate(_face(), _frame(120), "base") == (True, "ok")


def test_too_dark():
    assert _enr().evaluate(_face(), _frame(30), "base") == (False, "too_dark")


def test_too_bright():
    assert _enr().evaluate(_face(), _frame(220), "base") == (False, "too_bright")


def test_too_small():
    assert _enr().evaluate(_face(frac=0.01), _frame(120), "base") == (False, "too_small")


def test_too_close():
    assert _enr().evaluate(_face(frac=0.60), _frame(120), "base") == (False, "too_close")


def test_off_center():
    assert _enr().evaluate(_face(cx=0.85), _frame(120), "base") == (False, "off_center")


def test_low_score():
    assert _enr().evaluate(_face(det_score=0.5), _frame(120), "base") == (False, "low_score")


def test_brightness_beats_distance():
    """多项不合格时,优先报亮度(在距离之前)。"""
    f = _face(frac=0.60)  # 同时太近
    assert _enr().evaluate(f, _frame(30), "base") == (False, "too_dark")


def test_base_rejects_off_angle():
    assert _enr().evaluate(_face(yaw=0.30), _frame(120), "base") == (False, "face_straight")


def test_base_accepts_frontal():
    assert _enr().evaluate(_face(yaw=0.0), _frame(120), "base") == (True, "ok")


def test_angle_rejects_frontal():
    assert _enr().evaluate(_face(yaw=0.0), _frame(120), "angle") == (False, "turn_head")


def test_angle_accepts_turned():
    assert _enr().evaluate(_face(yaw=0.30), _frame(120), "angle") == (True, "ok")
