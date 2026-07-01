"""录入:采集多帧合格人脸,取平均特征。"""
from __future__ import annotations

import numpy as np

from .detector import DetectedFace, FaceDetector

_MIN_DET_SCORE = 0.6
_MIN_FACE_FRAC = 0.04   # 人脸面积至少占画面比例,过滤太远/太小
_MAX_FACE_FRAC = 0.55   # 人脸面积上限:太近会糊/出框,降低识别质量
_MIN_BRIGHTNESS = 60    # 人脸 ROI 灰度均值下限(0~255):太暗
_MAX_BRIGHTNESS = 200   # 上限:太亮/背光过曝
_MAX_OFF_CENTER = 0.22  # 人脸中心相对画面中心的最大偏移(按画面宽/高归一化)
_FRONTAL_MAX = 0.12     # 首条录入:|yaw| 超此判过偏(要正脸)
_TURN_MIN = 0.18        # 补录角度:|yaw| 低于此判不够侧(要转头)


def _roi_brightness(face: DetectedFace, frame_bgr) -> float:
    """人脸 ROI 的灰度均值(0~255)。ROI 取 bbox 与画面交集,空则回 -1。"""
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = (int(v) for v in face.bbox)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return -1.0
    roi = frame_bgr[y1:y2, x1:x2]
    return float(roi.mean())  # BGR 三通道均值近似亮度,够用(不必转灰度)


def _yaw_ratio(face: DetectedFace) -> float:
    """粗略偏转:鼻尖相对双眼中点的横向偏移 / 眼距。正脸≈0,转头变大;符号表方向。"""
    le, re, nose = face.kps[0], face.kps[1], face.kps[2]
    eye_mid_x = (le[0] + re[0]) / 2.0
    inter_eye = abs(re[0] - le[0])
    if inter_eye < 1e-3:
        return 0.0
    return float((nose[0] - eye_mid_x) / inter_eye)


class Enroller:
    """逐帧喂入,累积合格帧的特征;够数后给出平均归一化特征。"""

    def __init__(self, detector: FaceDetector, target_samples: int):
        self.detector = detector
        self.target = target_samples
        self._embeddings: list[np.ndarray] = []

    def evaluate(self, face: DetectedFace, frame_bgr, mode: str = "base") -> tuple[bool, str]:
        """纯判定:该脸是否合格作录入样本。返回 (ok, reason)。
        reason ∈ {"ok","too_dark","too_bright","too_close","too_small","off_center",
                  "low_score","face_straight","turn_head"}。
        mode="base"(首条,要正脸)/ "angle"(补录,要侧脸)。阈值集中此处,**只在控制台录入路径调用**。

        优先级(多项不合格报最该先修的):亮度 > 距离 > 居中 > 清晰度 > 姿态。
        """
        h, w = frame_bgr.shape[:2]
        # 亮度
        b = _roi_brightness(face, frame_bgr)
        if 0 <= b < _MIN_BRIGHTNESS:
            return False, "too_dark"
        if b > _MAX_BRIGHTNESS:
            return False, "too_bright"
        # 距离(面积占比)
        frac = face.area / float(w * h)
        if frac < _MIN_FACE_FRAC:
            return False, "too_small"
        if frac > _MAX_FACE_FRAC:
            return False, "too_close"
        # 居中(bbox 中心相对画面中心,按各自尺寸归一化)
        x1, y1, x2, y2 = face.bbox
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        if abs(cx / w - 0.5) > _MAX_OFF_CENTER or abs(cy / h - 0.5) > _MAX_OFF_CENTER:
            return False, "off_center"
        # 清晰度
        if face.det_score < _MIN_DET_SCORE:
            return False, "low_score"
        # 姿态门(分模式)
        yaw = abs(_yaw_ratio(face))
        if mode == "base" and yaw > _FRONTAL_MAX:
            return False, "face_straight"
        if mode == "angle" and yaw < _TURN_MIN:
            return False, "turn_head"
        return True, "ok"

    def add(self, face: DetectedFace) -> None:
        """采纳一帧合格人脸的特征。"""
        self._embeddings.append(face.embedding)

    def feed(self, frame_bgr, mode: str = "base") -> tuple[bool, DetectedFace | None]:
        """返回 (本帧是否被采纳, 检到的最大人脸或 None)。"""
        face = self.detector.largest_face(frame_bgr)
        if face is None:
            return False, None
        ok, _ = self.evaluate(face, frame_bgr, mode)
        if ok:
            self.add(face)
        return ok, face

    @property
    def collected(self) -> int:
        return len(self._embeddings)

    @property
    def done(self) -> bool:
        return self.collected >= self.target

    def result(self) -> np.ndarray:
        """平均后重新 L2 归一化,作为注册模板。"""
        if not self._embeddings:
            raise RuntimeError("无可用样本")
        mean = np.mean(self._embeddings, axis=0)
        n = np.linalg.norm(mean)
        return (mean / n).astype(np.float32) if n > 0 else mean.astype(np.float32)
