"""后台工作线程:把摄像头 + 模型推理放到 QThread,避免卡死 UI。"""
from __future__ import annotations

import time

import cv2
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from face_hello.auth import AuthResult, AuthSession
from face_hello.camera import Camera
from face_hello.detector import FaceDetector
from face_hello.enroll import Enroller
from face_hello.store import FaceStore

_FRAME_INTERVAL = 0.03  # 限制循环频率,约 30fps 上限


def bgr_to_qimage(frame) -> QImage:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    return QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()


class WarmupWorker(QThread):
    """启动时后台预热模型,避免首次录入/解锁卡顿。

    需预热两条链路:
      - InsightFace(识别):付 onnxruntime 冷启动;
      - MediaPipe FaceLandmarker(活体):首个实例要付 ~0.7s 进程级 TFLite 初始化。
    """

    ready = Signal()

    def __init__(self, detector: FaceDetector):
        super().__init__()
        self.detector = detector

    def run(self) -> None:
        try:
            self.detector.load()
        except Exception:  # noqa: BLE001 预热失败不致命,后续用时再报
            pass
        try:
            import numpy as np

            from face_hello.liveness import FaceMeshTracker

            tracker = FaceMeshTracker()
            tracker.process(np.zeros((480, 640, 3), dtype=np.uint8))
            tracker.close()
        except Exception:  # noqa: BLE001
            pass
        self.ready.emit()


class EnrollWorker(QThread):
    """录入:先快速拍 N 张原始帧(预览流畅),再统一处理提特征。"""

    preview = Signal(QImage)
    progress = Signal(int, int)       # captured, target
    status = Signal(str)              # 阶段文案
    finished_ok = Signal(object)      # np.ndarray embedding
    failed = Signal(str)

    def __init__(self, detector: FaceDetector, samples: int, capture_interval: float = 0.4):
        super().__init__()
        self.detector = detector
        self.samples = samples
        self.interval = capture_interval
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            frames = self._capture()
            if self._stop:
                self.failed.emit("已取消")
                return
            self._process(frames)
        except Exception as e:  # noqa: BLE001 原型阶段直接上抛文案
            self.failed.emit(str(e))

    def _capture(self) -> list:
        """阶段一:只采集原始帧,不做检测,保证预览流畅。"""
        frames: list = []
        with Camera() as cam:
            self.status.emit("正对镜头,开始拍摄…")
            next_cap = time.monotonic()
            while not self._stop and len(frames) < self.samples:
                frame = cam.read()
                self.preview.emit(bgr_to_qimage(frame))
                now = time.monotonic()
                if now >= next_cap:
                    frames.append(frame.copy())
                    self.progress.emit(len(frames), self.samples)
                    next_cap = now + self.interval
                time.sleep(_FRAME_INTERVAL)
        return frames

    def _process(self, frames: list) -> None:
        """阶段二:统一对已拍帧提特征、取平均。"""
        self.status.emit("处理中…")
        enr = Enroller(self.detector, self.samples)
        for f in frames:
            enr.feed(f)
        need = max(3, self.samples // 2)
        if enr.collected < need:
            self.failed.emit(
                f"有效人脸帧太少({enr.collected}/{len(frames)})——请正对镜头、光线充足后重试"
            )
            return
        self.finished_ok.emit(enr.result())


class AuthWorker(QThread):
    """测试解锁:活体挑战 → 识别比对。"""

    preview = Signal(QImage)
    instruction = Signal(str)
    finished_result = Signal(object)  # AuthResult
    failed = Signal(str)

    def __init__(self, detector: FaceDetector, store: FaceStore):
        super().__init__()
        self.detector = detector
        self.store = store
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            session = AuthSession(self.detector, self.store)
            last_instr = ""
            with Camera() as cam:
                while not self._stop and not session.done:
                    frame = cam.read()
                    session.feed(frame)
                    self.preview.emit(bgr_to_qimage(frame))
                    if session.instruction != last_instr:
                        last_instr = session.instruction
                        self.instruction.emit(last_instr)
                    time.sleep(_FRAME_INTERVAL)
            if session.done and session.result is not None:
                self.finished_result.emit(session.result)
            else:
                self.finished_result.emit(AuthResult(False, "已取消"))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
