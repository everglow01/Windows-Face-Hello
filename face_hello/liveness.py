"""活体检测:眨眼(EAR)+ 转头(头姿 yaw)主动挑战。

用 MediaPipe FaceMesh 取 468 关键点:
  - EAR(眼睛纵横比)判定眨眼;
  - solvePnP 估头姿,yaw 判定左右转头。
随机挑战 + 超时,挡静态照片 / 简单回放。
"""
from __future__ import annotations

import enum
import random
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import config

# FaceMesh 眼部 6 点(p1 外角, p2 上, p3 上, p4 内角, p5 下, p6 下)
LEFT_EYE = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]

# solvePnP 用的 FaceMesh 索引(对应下方 3D 模型点)
POSE_IDX = [1, 152, 33, 263, 61, 291]  # 鼻尖, 下巴, 左眼外角, 右眼外角, 左嘴角, 右嘴角
# 通用人脸 3D 模型点(单位近似 mm),与 POSE_IDX 一一对应
MODEL_POINTS = np.array(
    [
        (0.0, 0.0, 0.0),        # 鼻尖
        (0.0, -63.6, -12.5),    # 下巴
        (-43.3, 32.7, -26.0),   # 左眼外角
        (43.3, 32.7, -26.0),    # 右眼外角
        (-28.9, -28.9, -24.1),  # 左嘴角
        (28.9, -28.9, -24.1),   # 右嘴角
    ],
    dtype=np.float64,
)


def _ear(pts: np.ndarray) -> float:
    """pts: 6x2 像素坐标,按 [外角,上,上,内角,下,下] 顺序。"""
    p1, p2, p3, p4, p5, p6 = pts
    vert = np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)
    horiz = 2.0 * np.linalg.norm(p1 - p4)
    return float(vert / horiz) if horiz > 0 else 0.0


@dataclass
class FaceMetrics:
    ear: float          # 双眼平均 EAR
    yaw_deg: float      # 头部偏航角(>0 右转 / <0 左转,实测后可能需翻转)


def _download_landmarker_bytes() -> bytes:
    """下载 face_landmarker.task,缓存到 models/ 并返回字节。"""
    import urllib.request

    config.ensure_dirs()
    urllib.request.urlretrieve(config.FACE_LANDMARKER_URL, config.FACE_LANDMARKER)
    return config.FACE_LANDMARKER.read_bytes()


class FaceMeshTracker:
    """逐帧提取 EAR 与头姿。无人脸时 process 返回 None。

    用 MediaPipe Tasks API 的 FaceLandmarker(0.10.x 已移除 legacy solutions)。
    """

    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        # 用 buffer 而非 path:mediapipe C++ 打不开含非 ASCII(如中文)的 Windows 路径
        model_bytes = config.FACE_LANDMARKER.read_bytes() if config.FACE_LANDMARKER.exists() \
            else _download_landmarker_bytes()
        options = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_buffer=model_bytes),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=1,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)

    def process(self, frame_bgr) -> FaceMetrics | None:
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        res = self._landmarker.detect(mp_image)
        if not res.face_landmarks:
            return None
        lm = res.face_landmarks[0]
        pts = np.array([(p.x * w, p.y * h) for p in lm], dtype=np.float64)

        ear = (_ear(pts[LEFT_EYE]) + _ear(pts[RIGHT_EYE])) / 2.0
        yaw = self._estimate_yaw(pts[POSE_IDX], (w, h))
        return FaceMetrics(ear=ear, yaw_deg=yaw)

    @staticmethod
    def _estimate_yaw(image_points: np.ndarray, size: tuple[int, int]) -> float:
        w, h = size
        focal = float(w)
        cam = np.array([[focal, 0, w / 2.0], [0, focal, h / 2.0], [0, 0, 1]], dtype=np.float64)
        ok, rvec, _ = cv2.solvePnP(
            MODEL_POINTS, image_points, cam, np.zeros((4, 1)),
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not ok:
            return 0.0
        rmat, _ = cv2.Rodrigues(rvec)
        sy = np.sqrt(rmat[0, 0] ** 2 + rmat[1, 0] ** 2)
        yaw = np.degrees(np.arctan2(-rmat[2, 0], sy))
        return float(yaw)

    def close(self) -> None:
        self._landmarker.close()


class ChallengeKind(enum.Enum):
    BLINK = "blink"
    TURN_LEFT = "turn_left"
    TURN_RIGHT = "turn_right"


@dataclass
class LivenessSession:
    """一次活体挑战的状态机。逐帧喂 FaceMetrics,读 instruction/done/passed。"""

    settings: dict
    kind: ChallengeKind = field(init=False)
    created_ts: float = field(init=False)        # 会话创建时刻(用于"一直没脸"总超时)
    start_ts: float | None = field(default=None, init=False)  # 首次见到人脸才开始挑战计时
    done: bool = field(default=False, init=False)
    passed: bool = field(default=False, init=False)

    # 眨眼计数内部状态
    _blinks: int = field(default=0, init=False)
    _closed_frames: int = field(default=0, init=False)
    _was_closed: bool = field(default=False, init=False)

    def __post_init__(self):
        self.kind = random.choice(
            [ChallengeKind.BLINK, ChallengeKind.TURN_LEFT, ChallengeKind.TURN_RIGHT]
        )
        self.created_ts = time.monotonic()

    @property
    def instruction(self) -> str:
        if self.start_ts is None:
            return "请正对摄像头…"
        if self.kind is ChallengeKind.BLINK:
            need = self.settings.get("required_blinks", 2)
            return f"请眨眼 {need} 次({self._blinks}/{need})"
        if self.kind is ChallengeKind.TURN_LEFT:
            return "请向左转头"
        return "请向右转头"

    def update(self, metrics: FaceMetrics | None) -> None:
        if self.done:
            return
        now = time.monotonic()

        # 还没见到人脸:不计挑战时间,但有"一直没脸"的总超时兜底
        if self.start_ts is None:
            if metrics is None:
                if now - self.created_ts > self.settings.get("no_face_timeout_s", 15.0):
                    self.done, self.passed = True, False
                return
            self.start_ts = now  # 人脸首次出现,挑战计时从此刻起

        if now - self.start_ts > self.settings.get("challenge_timeout_s", 6.0):
            self.done, self.passed = True, False
            return
        if metrics is None:
            return

        if self.kind is ChallengeKind.BLINK:
            self._update_blink(metrics)
        else:
            self._update_turn(metrics)

    def _update_blink(self, m: FaceMetrics) -> None:
        thr = self.settings.get("ear_threshold", 0.21)
        consec = self.settings.get("ear_consec_frames", 2)
        if m.ear < thr:
            self._closed_frames += 1
            self._was_closed = self._closed_frames >= consec
        else:
            if self._was_closed:
                self._blinks += 1
            self._closed_frames = 0
            self._was_closed = False
        if self._blinks >= self.settings.get("required_blinks", 2):
            self.done, self.passed = True, True

    def _update_turn(self, m: FaceMetrics) -> None:
        thr = self.settings.get("yaw_threshold_deg", 18.0)
        if self.kind is ChallengeKind.TURN_RIGHT and m.yaw_deg > thr:
            self.done, self.passed = True, True
        elif self.kind is ChallengeKind.TURN_LEFT and m.yaw_deg < -thr:
            self.done, self.passed = True, True
