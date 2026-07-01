"""Enroller 的质量门:evaluate(合格/偏小/低分)、add、feed 向后兼容、result 归一化。

纯逻辑,无摄像头/真模型:用合成 embedding + 真 DetectedFace(评估读 .det_score/.area),
feed 用例配 conftest 的 FakeDetector 注入预设人脸。
"""
from __future__ import annotations

import numpy as np

from conftest import FakeDetector, _frontal_kps, unit_vec

from face_hello.detector import DetectedFace
from face_hello.enroll import Enroller

_W, _H = 640, 480  # 面积 307200;4% 门槛 = 12288 像素
FRAME = np.full((_H, _W, 3), 120, dtype=np.uint8)  # 均匀中等亮度,过亮度门


def _face(det_score: float, side: int) -> DetectedFace:
    """造一张边长 side、置信度 det_score 的**居中**正脸(area = side²)。"""
    half = side / 2.0
    cx, cy = _W / 2.0, _H / 2.0
    return DetectedFace(
        bbox=np.array([cx - half, cy - half, cx + half, cy + half]),
        embedding=unit_vec(1, 0),
        det_score=det_score,
        kps=_frontal_kps(),
    )


def test_evaluate_ok():
    enr = Enroller(FakeDetector(), target_samples=3)
    assert enr.evaluate(_face(0.9, 200), FRAME) == (True, "ok")  # area 40000 ≥ 12288


def test_evaluate_too_small():
    enr = Enroller(FakeDetector(), target_samples=3)
    # 置信度够但脸太小(area 2500 < 12288)
    assert enr.evaluate(_face(0.9, 50), FRAME) == (False, "too_small")


def test_evaluate_low_score_takes_priority():
    enr = Enroller(FakeDetector(), target_samples=3)
    # 低分先判(在姿态门之前):即便脸够大也按 low_score 拒
    assert enr.evaluate(_face(0.3, 200), FRAME) == (False, "low_score")


def test_add_increments_collected_and_done():
    enr = Enroller(FakeDetector(), target_samples=2)
    assert enr.collected == 0 and enr.done is False
    enr.add(_face(0.9, 200))
    assert enr.collected == 1 and enr.done is False
    enr.add(_face(0.9, 200))
    assert enr.collected == 2 and enr.done is True


def test_feed_accepts_good_face():
    face = _face(0.9, 200)
    enr = Enroller(FakeDetector(face=face), target_samples=3)
    accepted, returned = enr.feed(FRAME)
    assert accepted is True and returned is face and enr.collected == 1


def test_feed_rejects_small_face_without_collecting():
    face = _face(0.9, 50)
    enr = Enroller(FakeDetector(face=face), target_samples=3)
    accepted, returned = enr.feed(FRAME)
    assert accepted is False and returned is face and enr.collected == 0


def test_feed_no_face():
    enr = Enroller(FakeDetector(face=None), target_samples=3)
    accepted, returned = enr.feed(FRAME)
    assert accepted is False and returned is None and enr.collected == 0


def test_result_is_l2_normalized():
    enr = Enroller(FakeDetector(), target_samples=2)
    enr.add(_face(0.9, 200))
    enr.add(DetectedFace(bbox=np.array([0, 0, 200, 200]), embedding=unit_vec(0, 1),
                         det_score=0.9, kps=_frontal_kps()))
    r = enr.result()
    assert abs(float(np.linalg.norm(r)) - 1.0) < 1e-5
