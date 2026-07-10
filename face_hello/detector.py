"""人脸检测 + 特征提取(InsightFace / ArcFace, CPU)。"""
from __future__ import annotations

import threading
import warnings
from dataclasses import dataclass

import numpy as np

from . import config

# InsightFace 内部用到的旧 numpy/skimage 接口,只是 FutureWarning,屏蔽噪音
warnings.filterwarnings("ignore", category=FutureWarning, module=r"insightface\..*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"insightface\..*")


def _sample_face_image():
    """读 insightface 自带的样例人脸图(预热用)。

    用 np.fromfile + imdecode 而非 cv2.imread:后者在 Windows 读不了含中文的路径。
    """
    import os

    import cv2
    import insightface

    path = os.path.join(os.path.dirname(insightface.__file__), "data", "images", "t1.jpg")
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


@dataclass
class DetectedFace:
    bbox: np.ndarray          # [x1, y1, x2, y2]
    embedding: np.ndarray     # 512 维,已 L2 归一化(normed_embedding)
    det_score: float
    kps: np.ndarray           # 5×2 关键点:左眼/右眼/鼻/左嘴角/右嘴角(录入质量引导用)

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox
        return float(max(0, x2 - x1) * max(0, y2 - y1))


class FaceDetector:
    """封装 InsightFace FaceAnalysis,惰性加载模型。"""

    def __init__(self, model_name: str = config.INSIGHTFACE_MODEL):
        self.model_name = model_name
        self._app = None  # 惰性,避免导入即加载
        self._lock = threading.Lock()  # 防止预加载与首次推理并发重复加载
        self._inference_lock = threading.Lock()

    def load(self) -> None:
        """显式加载并真正跑一次推理预热(供启动时后台调用)。

        只 prepare 不推理的话,解锁时第一次 get() 要付 onnxruntime 冷启动代价。
        """
        import logging
        import time

        log = logging.getLogger("facehello")
        t0 = time.perf_counter()
        app = self._ensure_loaded()  # 读模型 + 建 onnxruntime 会话(191MB 冷读疑似大头)
        t1 = time.perf_counter()
        log.info("[计时] detector 读模型+建会话 %.2fs", t1 - t0)
        try:
            with self._inference_lock:
                app.get(_sample_face_image())  # 带人脸的样例图,预热检测+识别两条链路
        except Exception:  # noqa: BLE001 预热失败不致命
            pass
        log.info("[计时] detector 样例推理预热 %.2fs", time.perf_counter() - t1)

    def _ensure_loaded(self):
        with self._lock:
            if self._app is None:
                from insightface.app import FaceAnalysis

                config.ensure_dirs()
                app = FaceAnalysis(
                    name=self.model_name,
                    root=str(config.MODELS_DIR.parent),  # 模型缓存到项目下
                    # 只留检测+识别,关掉 genderage / 2d106 / 3d68,省一半以上算力
                    allowed_modules=["detection", "recognition"],
                    providers=["CPUExecutionProvider"],
                )
                app.prepare(ctx_id=-1, det_size=config.DET_SIZE)  # ctx_id=-1 -> CPU
                self._app = app
        return self._app

    def detect(self, frame_bgr) -> list[DetectedFace]:
        app = self._ensure_loaded()
        with self._inference_lock:
            faces = app.get(frame_bgr)
        out: list[DetectedFace] = []
        for f in faces:
            out.append(
                DetectedFace(
                    bbox=f.bbox.astype(float),
                    embedding=np.asarray(f.normed_embedding, dtype=np.float32),
                    det_score=float(f.det_score),
                    kps=np.asarray(f.kps, dtype=np.float32),  # 检测本就算好,仅存一下,解锁路径不评估
                )
            )
        return out

    def largest_face(self, frame_bgr) -> DetectedFace | None:
        faces = self.detect(frame_bgr)
        if not faces:
            return None
        return max(faces, key=lambda f: f.area)
