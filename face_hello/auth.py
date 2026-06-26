"""认证编排:先活体挑战,通过后再识别比对。

AuthSession 为逐帧状态机,供 Qt(QTimer/线程)或 CLI 循环驱动。
"""
from __future__ import annotations

from dataclasses import dataclass

from .detector import FaceDetector
from .i18n import t
from .liveness import FaceMeshTracker, LivenessSession
from .matcher import best_match_with_margin
from .store import FaceStore


@dataclass
class AuthResult:
    success: bool
    reason: str
    name: str | None = None
    similarity: float = 0.0
    # True = 真生物特征结果(匹配/不匹配/歧义/活体/未见人脸),计入失败锁定;
    # 基础设施错误(未录入、摄像头不可用、异常)为 False,不计数。
    biometric: bool = False


class AuthSession:
    """一次认证:liveness -> recognize -> done。"""

    def __init__(self, detector: FaceDetector, store: FaceStore, tracker: FaceMeshTracker | None = None):
        self.detector = detector
        self.settings = store.get_settings()
        self._lang = self.settings.get("language", "zh")
        self._gallery = store.embeddings()
        self._profiles = store.list_profiles()
        self.result: AuthResult | None = None
        # 被动反欺骗(独立于主动活体;关了活体也照样守门)。模型懒加载在 _antispoof_gate。
        self._antispoof_on = self.settings.get("antispoof_enabled", True)
        self._antispoof_thr = self.settings.get("antispoof_threshold", 0.55)
        self._antispoof_max = self.settings.get("antispoof_max_frames", 10)
        self._spoof_cleared = False  # 反欺骗门已放行(判真 / fail-open),后续帧直接进识别
        self._spoof_tries = 0        # 反欺骗已采样帧数(达 _antispoof_max 仍无脸则 fail-open)
        # 活体可关:关掉则不建 tracker,直接进识别阶段
        if self.settings.get("liveness_enabled", True):
            # 传入 tracker(服务的长寿命共享实例)则复用、不负责关;否则各会话自建并在 _finish 关。
            if tracker is not None:
                self._tracker = tracker
                self._owns_tracker = False
            else:
                self._tracker = FaceMeshTracker()
                self._owns_tracker = True
            self._liveness = LivenessSession(self.settings)
            self.phase = "liveness"  # liveness | recognize | done
        else:
            self._tracker = None
            self._owns_tracker = False
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
                    self._finish(AuthResult(False, t("liveness_failed", self._lang), biometric=True))
                    return
                self.phase = "recognize"
        if self.phase == "recognize":  # 活体通过 或 活体关闭,都在此识别
            self._recognize(frame_bgr)

    def _recognize(self, frame_bgr) -> None:
        # 反欺骗门先行:翻拍/假体在比对前就拒掉。模型在则需逐帧采样到判定才放行
        # (避免单帧没检到脸就 fail-open);判假直接 _finish,本帧不进识别。
        if self._antispoof_on and not self._spoof_cleared:
            if not self._antispoof_gate(frame_bgr):
                return
        face = self.detector.largest_face(frame_bgr)
        if face is None:
            self._finish(AuthResult(False, t("no_face", self._lang), biometric=True))
            return
        names = [p.name for p in self._profiles]
        idx, sim, margin = best_match_with_margin(face.embedding, self._gallery, names)
        thr = self.settings["match_threshold"]
        min_margin = self.settings.get("match_margin", 0.0)
        if idx < 0 or sim < thr:
            self._finish(
                AuthResult(False, t("face_mismatch", self._lang, sim=sim, thr=thr), None, sim, biometric=True)
            )
        elif margin < min_margin:
            # 过了阈值但与「另一个人」贴得太近——多账户下宁可拒绝也不解错账户
            self._finish(
                AuthResult(False, t("ambiguous_match", self._lang, margin=margin, m=min_margin), None, sim, biometric=True)
            )
        else:
            self._finish(AuthResult(True, t("auth_pass", self._lang), names[idx], sim, biometric=True))

    def _antispoof_gate(self, frame_bgr) -> bool:
        """逐帧反欺骗门。返回 True=放行(判真 / fail-open),可进入识别;
        False=尚无定论(继续采下一帧)或已判假体并 _finish(此时 phase 已 done)。

        - 模型不可用 / 推理异常 = 基础设施错误 → 立刻 fail-open(同缺模型,红线:不锁死用户);
        - score < 阈值(检到脸、判假)→ 立刻拒(确认假体,不给更多机会);
        - score ≥ 阈值(检到脸、判真)→ 放行;
        - score = None(这帧 RetinaFace 没检到脸)→ 暂不定论,继续采样,
          连续 _antispoof_max 帧仍没检到才 fail-open(堵住单帧漏检就跳过反欺骗)。
        """
        from .antispoof import get_antispoof

        model = get_antispoof()
        if model is None:
            self._spoof_cleared = True
            return True
        try:
            real = model.score(frame_bgr)  # 自带 RetinaFace 检测+裁剪
        except Exception:  # noqa: BLE001 运行时异常也 fail-open
            self._spoof_cleared = True
            return True
        self._spoof_tries += 1
        if real is not None:
            if real < self._antispoof_thr:
                self._finish(
                    AuthResult(False, t("spoof_detected", self._lang, p=real), None, biometric=True)
                )
                return False
            self._spoof_cleared = True  # 判真
            return True
        if self._spoof_tries >= self._antispoof_max:  # 连续没检到脸达上限 → fail-open
            self._spoof_cleared = True
            return True
        return False  # 这帧没检到脸,继续采样

    def _finish(self, result: AuthResult) -> None:
        self.result = result
        self.phase = "done"
        if self._tracker is not None and self._owns_tracker:
            # 只关自己建的 tracker;注入的(服务长寿命共享实例)留给持有者复用。
            # MediaPipe 的 close() 会阻塞约 40s(等内部图/线程退出),丢到后台守护线程,
            # 不卡解锁主流程。
            import threading

            threading.Thread(target=self._tracker.close, daemon=True).start()
            self._tracker = None


def authenticate_blocking(
    detector: FaceDetector, store: FaceStore, on_instruction=None, camera_timeout_s: float = 8.0,
    tracker: FaceMeshTracker | None = None,
) -> AuthResult:
    """无界面认证:开摄像头跑完整 liveness→识别,返回结果。

    供认证服务调用(无 Qt)。liveness 自带超时,循环必然结束。
    on_instruction(text):活体提示变化时回调(服务端可打印,供测试者照做)。
    camera_timeout_s:锁屏路径用短超时,摄像头缺失/被占时快速回退到密码,而非干等 30s。
    tracker:服务的长寿命共享 FaceMeshTracker;传入则复用(不在会话结束时关),None 则各会话自建。
    """
    import logging
    import time

    from .camera import Camera

    log = logging.getLogger("facehello")
    session = AuthSession(detector, store, tracker=tracker)
    last = None
    idx = int(store.get_settings().get("camera_index", 0))
    cam = Camera(idx)
    _t0 = time.perf_counter()
    cam.open(timeout_s=camera_timeout_s)
    _t_cam = time.perf_counter()
    log.info("[计时] 解锁:摄像头打开 %.2fs", _t_cam - _t0)
    try:
        while not session.done:
            session.feed(cam.read())
            if on_instruction is not None and session.instruction != last:
                last = session.instruction
                on_instruction(session.instruction)
    finally:
        cam.release()
    log.info(
        "[计时] 解锁:总 %.2fs(摄像头打开 %.2fs + 活体&识别 %.2fs)",
        time.perf_counter() - _t0, _t_cam - _t0, time.perf_counter() - _t_cam,
    )
    if session.result is not None:
        return session.result
    return AuthResult(False, t("incomplete", session._lang))
