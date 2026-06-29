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
from face_hello.i18n import tr
from face_hello.matcher import best_match
from face_hello.store import FaceStore

_FRAME_INTERVAL = 0.03  # 限制循环频率,约 30fps 上限

# 引导预览框颜色(BGR):合格=绿、偏小/偏暗=黄
_BOX_OK = (0, 200, 0)
_BOX_BAD = (0, 180, 255)


def bgr_to_qimage(frame) -> QImage:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    return QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()


def _draw_face_box(frame, face, color) -> None:
    """在帧上画人脸框 + ASCII 的 det_score(中文不进 cv2,见仓库中文路径坑)。"""
    x1, y1, x2, y2 = (int(v) for v in face.bbox)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    cv2.putText(frame, f"{face.det_score:.2f}", (x1, max(y1 - 8, 14)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


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
        try:
            from face_hello.antispoof import get_antispoof

            m = get_antispoof()  # 模型缺失返回 None(fail-open),不报错
            if m is not None:
                m.load()
        except Exception:  # noqa: BLE001
            pass
        self.ready.emit()


class EnrollWorker(QThread):
    """录入:逐帧检测做实时引导,只在间隔到点且人脸合格时采纳一帧。"""

    preview = Signal(QImage)              # 帧上已画人脸框
    guidance = Signal(str, int, int)      # (reason_key, collected, target)
    finished_ok = Signal(object)          # np.ndarray embedding
    failed = Signal(str)

    _TIMEOUT_S = 60.0  # 总时长上限:迟迟采不到足够人脸就放弃,不无限等

    def __init__(self, detector: FaceDetector, samples: int, capture_interval: float = 0.4,
                 camera_index: int = 0):
        super().__init__()
        self.detector = detector
        self.samples = samples
        self.interval = capture_interval
        self.camera_index = camera_index
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            enr = Enroller(self.detector, self.samples)
            deadline = time.monotonic() + self._TIMEOUT_S
            next_cap = time.monotonic()
            with Camera(self.camera_index) as cam:
                while not self._stop and not enr.done:
                    if time.monotonic() > deadline:
                        self.failed.emit(tr("enroll_timeout"))
                        return
                    frame = cam.read()
                    face = self.detector.largest_face(frame)
                    if face is None:
                        key = "guidance_no_face"
                    else:
                        ok, reason = enr.evaluate(face, frame.shape)
                        if not ok:
                            key = "guidance_" + reason  # too_small / low_score
                            _draw_face_box(frame, face, _BOX_BAD)
                        else:
                            _draw_face_box(frame, face, _BOX_OK)
                            now = time.monotonic()
                            if now >= next_cap:
                                enr.add(face)
                                next_cap = now + self.interval
                                key = "guidance_captured"
                            else:
                                key = "guidance_hold_still"
                    self.preview.emit(bgr_to_qimage(frame))
                    self.guidance.emit(key, enr.collected, self.samples)
                    time.sleep(_FRAME_INTERVAL)
            if self._stop:
                self.failed.emit(tr("cancelled"))
                return
            self.finished_ok.emit(enr.result())
        except Exception as e:  # noqa: BLE001 原型阶段直接上抛文案
            self.failed.emit(str(e))


class SimilarityMonitorWorker(QThread):
    """实时比对(诊断用):逐帧算与录入模板的最佳余弦相似度,喂给直方图。

    刻意不跑活体/反欺骗、不产出解锁结果——只是看相似度分布,绝不接入真实解锁。
    """

    preview = Signal(QImage)          # 帧上已画人脸框 + 相似度数字
    sample = Signal(float)            # 当前帧最佳相似度;无脸发 -1.0
    failed = Signal(str)

    def __init__(self, detector: FaceDetector, store: FaceStore, camera_index: int = 0,
                 threshold: float = 0.0):
        super().__init__()
        self.detector = detector
        self.store = store
        self.camera_index = camera_index
        self.threshold = threshold  # 预览框绿/黄分界,与直方图同口径(match_threshold)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            gallery = [p.embedding for p in self.store.list_profiles()]
            with Camera(self.camera_index) as cam:
                while not self._stop:
                    frame = cam.read()
                    face = self.detector.largest_face(frame)
                    if face is None:
                        self.sample.emit(-1.0)
                    else:
                        _, sim = best_match(face.embedding, gallery)
                        color = _BOX_OK if sim >= self.threshold else _BOX_BAD
                        x1, y1, x2, y2 = (int(v) for v in face.bbox)
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        cv2.putText(frame, f"{sim:.3f}", (x1, max(y1 - 8, 14)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                        self.sample.emit(float(sim))
                    self.preview.emit(bgr_to_qimage(frame))
                    time.sleep(_FRAME_INTERVAL)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class AuthWorker(QThread):
    """测试解锁:活体挑战 → 识别比对。"""

    preview = Signal(QImage)
    instruction = Signal(str)
    finished_result = Signal(object)  # AuthResult
    failed = Signal(str)

    def __init__(self, detector: FaceDetector, store: FaceStore, camera_index: int = 0):
        super().__init__()
        self.detector = detector
        self.store = store
        self.camera_index = camera_index
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            session = AuthSession(self.detector, self.store)
            last_instr = ""
            with Camera(self.camera_index) as cam:
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
                self.finished_result.emit(AuthResult(False, tr("cancelled")))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class CameraTestWorker(QThread):
    """一次性抓一帧:供设置页「测试」按钮预览所选摄像头。短超时,无效 index 不干等。"""

    ok = Signal(QImage)
    failed = Signal(str)

    def __init__(self, index: int):
        super().__init__()
        self.index = index

    def run(self) -> None:
        cam = Camera(self.index)
        try:
            cam.open(timeout_s=3.0)
            self.ok.emit(bgr_to_qimage(cam.read()))
        except Exception as e:  # noqa: BLE001 打不开就回失败,UI 提示换索引
            self.failed.emit(str(e))
        finally:
            cam.release()
