"""录入:采集多帧合格人脸,取平均特征。"""
from __future__ import annotations

import numpy as np

from .detector import DetectedFace, FaceDetector

_MIN_DET_SCORE = 0.6
_MIN_FACE_FRAC = 0.04  # 人脸面积至少占画面比例,过滤太远/太小


class Enroller:
    """逐帧喂入,累积合格帧的特征;够数后给出平均归一化特征。"""

    def __init__(self, detector: FaceDetector, target_samples: int):
        self.detector = detector
        self.target = target_samples
        self._embeddings: list[np.ndarray] = []

    def evaluate(self, face: DetectedFace, frame_shape) -> tuple[bool, str]:
        """纯判定:该脸是否合格作录入样本。返回 (ok, reason)，
        reason ∈ {"ok","too_small","low_score"}。阈值集中此处。"""
        if face.det_score < _MIN_DET_SCORE:
            return False, "low_score"
        h, w = frame_shape[:2]
        if face.area < _MIN_FACE_FRAC * (w * h):
            return False, "too_small"
        return True, "ok"

    def add(self, face: DetectedFace) -> None:
        """采纳一帧合格人脸的特征。"""
        self._embeddings.append(face.embedding)

    def feed(self, frame_bgr) -> tuple[bool, DetectedFace | None]:
        """返回 (本帧是否被采纳, 检到的最大人脸或 None)。"""
        face = self.detector.largest_face(frame_bgr)
        if face is None:
            return False, None
        ok, _ = self.evaluate(face, frame_bgr.shape)
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
