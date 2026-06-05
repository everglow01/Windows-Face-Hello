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
        self._tracker = FaceMeshTracker()
        self._liveness = LivenessSession(self.settings)
        self.phase = "liveness"  # liveness | recognize | done
        self.result: AuthResult | None = None

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
                else:
                    self.phase = "recognize"
                    self._recognize(frame_bgr)

    def _recognize(self, frame_bgr) -> None:
        face = self.detector.largest_face(frame_bgr)
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
        self._tracker.close()


def authenticate_blocking(detector: FaceDetector, store: FaceStore, on_instruction=None) -> AuthResult:
    """无界面认证:开摄像头跑完整 liveness→识别,返回结果。

    供认证服务调用(无 Qt)。liveness 自带超时,循环必然结束。
    on_instruction(text):活体提示变化时回调(服务端可打印,供测试者照做)。
    """
    from .camera import Camera

    session = AuthSession(detector, store)
    last = None
    with Camera() as cam:
        while not session.done:
            session.feed(cam.read())
            if on_instruction is not None and session.instruction != last:
                last = session.instruction
                on_instruction(session.instruction)
    return session.result if session.result is not None else AuthResult(False, "未完成")
