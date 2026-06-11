"""认证编排:先活体挑战,通过后再识别比对。

AuthSession 为逐帧状态机,供 Qt(QTimer/线程)或 CLI 循环驱动。
"""
from __future__ import annotations

from dataclasses import dataclass

from .detector import FaceDetector
from .i18n import t
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
        self._lang = self.settings.get("language", "zh")
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
            return t("recognizing", self._lang)
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
                    self._finish(AuthResult(False, t("liveness_failed", self._lang)))
                    return
                self.phase = "recognize"
        if self.phase == "recognize":  # 活体通过 或 活体关闭,都在此识别
            self._recognize(frame_bgr)

    def _recognize(self, frame_bgr) -> None:
        face = self.detector.largest_face(frame_bgr)
        if face is None:
            self._finish(AuthResult(False, t("no_face", self._lang)))
            return
        idx, sim = best_match(face.embedding, self._gallery)
        thr = self.settings["match_threshold"]
        if idx >= 0 and sim >= thr:
            self._finish(AuthResult(True, t("auth_pass", self._lang), self._profiles[idx].name, sim))
        else:
            self._finish(
                AuthResult(False, t("face_mismatch", self._lang, sim=sim, thr=thr), None, sim)
            )

    def _finish(self, result: AuthResult) -> None:
        self.result = result
        self.phase = "done"
        if self._tracker is not None:
            # MediaPipe 的 close() 会阻塞约 40s(等内部图/线程退出),丢到后台守护线程,
            # 不卡解锁主流程。tracker 本身按会话新建,后台关旧的即可。
            import threading

            threading.Thread(target=self._tracker.close, daemon=True).start()
            self._tracker = None


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
    if session.result is not None:
        return session.result
    return AuthResult(False, t("incomplete", session._lang))
