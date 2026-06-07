"""认证编排:先活体挑战,通过后再识别比对。

AuthSession 为逐帧状态机,供 Qt(QTimer/线程)或 CLI 循环驱动。
"""
from __future__ import annotations

from dataclasses import dataclass

from .detector import FaceDetector
from .liveness import FaceMeshTracker, LivenessSession
from .matcher import best_match
from .store import FaceStore


@dataclass
class AuthResult:
    success: bool
    reason: str
    name: str | None = None
    similarity: float = 0.0


class AuthSession:
    """一次认证:liveness -> recognize -> done。"""

    def __init__(self, detector: FaceDetector, store: FaceStore):
        self.detector = detector
        self.settings = store.get_settings()
        self._gallery = store.embeddings()
        self._profiles = store.list_profiles()
        self.result: AuthResult | None = None
        # 活体可关:关掉则不建 tracker,直接进识别阶段
        if self.settings.get("liveness_enabled", True):
            self._tracker = FaceMeshTracker()
            self._liveness = LivenessSession(self.settings)
            self.phase = "liveness"  # liveness | recognize | done
        else:
            self._tracker = None
            self._liveness = None
            self.phase = "recognize"

    @property
    def instruction(self) -> str:
        if self.phase == "liveness":
            return self._liveness.instruction
        if self.phase == "recognize":
            return "识别中…"
        return self.result.reason if self.result else ""

    @property
    def done(self) -> bool:
        return self.phase == "done"

    def feed(self, frame_bgr) -> None:
        if self.phase == "done":
            return
        if self.phase == "liveness":
            self._liveness.update(self._tracker.process(frame_bgr))
            if self._liveness.done:
                if not self._liveness.passed:
                    self._finish(AuthResult(False, "活体检测失败(超时或未完成动作)"))
                    return
                self.phase = "recognize"
                # 识别前先关掉 MediaPipe:其线程池与 onnxruntime 同时活动会让识别卡死数十秒
                if self._tracker is not None:
                    import time

                    _tc = time.monotonic()
                    self._tracker.close()
                    _dc = time.monotonic() - _tc
                    if _dc > 0.5:  # 临时诊断:确认 close 是否就是那 ~42s
                        print(f"[perf] tracker_close={_dc:.2f}s", flush=True)
                    self._tracker = None
        if self.phase == "recognize":  # 活体通过 或 活体关闭,都在此识别
            self._recognize(frame_bgr)

    def _recognize(self, frame_bgr) -> None:
        import time

        _t = time.monotonic()
        face = self.detector.largest_face(frame_bgr)
        _d = time.monotonic() - _t
        if _d > 0.5:  # 临时诊断:确认识别耗时
            print(f"[perf] recognize={_d:.2f}s", flush=True)
        if face is None:
            self._finish(AuthResult(False, "未检测到人脸"))
            return
        idx, sim = best_match(face.embedding, self._gallery)
        thr = self.settings["match_threshold"]
        if idx >= 0 and sim >= thr:
            self._finish(AuthResult(True, "认证通过", self._profiles[idx].name, sim))
        else:
            self._finish(AuthResult(False, f"人脸不匹配(相似度 {sim:.3f} < {thr:.2f})", None, sim))

    def _finish(self, result: AuthResult) -> None:
        self.result = result
        self.phase = "done"
        if self._tracker is not None:
            self._tracker.close()


def authenticate_blocking(detector: FaceDetector, store: FaceStore, on_instruction=None) -> AuthResult:
    """无界面认证:开摄像头跑完整 liveness→识别,返回结果。

    供认证服务调用(无 Qt)。liveness 自带超时,循环必然结束。
    on_instruction(text):活体提示变化时回调(服务端可打印,供测试者照做)。
    """
    import time

    from .camera import Camera

    session = AuthSession(detector, store)
    last = None
    with Camera() as cam:
        while not session.done:
            t0 = time.monotonic()
            frame = cam.read()
            t1 = time.monotonic()
            session.feed(frame)
            t2 = time.monotonic()
            if (t1 - t0) > 0.5 or (t2 - t1) > 0.5:  # 临时诊断:定位每帧慢在哪
                print(f"[perf] read={t1 - t0:.2f}s feed={t2 - t1:.2f}s", flush=True)
            if on_instruction is not None and session.instruction != last:
                last = session.instruction
                on_instruction(session.instruction)
    return session.result if session.result is not None else AuthResult(False, "未完成")
