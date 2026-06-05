"""集中配置:路径、模型、阈值。

非敏感运行参数(阈值/renew_days 等)可被 store 中的 settings 覆盖;
敏感数据(人脸特征)由 store.py 走 DPAPI 加密单独存放。
"""
from __future__ import annotations

from pathlib import Path

# 项目根:face_hello/config.py -> 上两级
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models"
FACE_STORE = DATA_DIR / "faces.dat"  # DPAPI 加密的人脸库

# 认证服务的命名管道(Credential Provider 通过它请求认证)
PIPE_NAME = r"\\.\pipe\FaceHello"

# 识别模型
INSIGHTFACE_MODEL = "buffalo_l"
DET_SIZE = (320, 320)  # 贴脸的摄像头 320 足够,比 640 快得多

# 活体用的 MediaPipe FaceLandmarker 模型(Tasks API,首次自动下载)
FACE_LANDMARKER = MODELS_DIR / "face_landmarker.task"
FACE_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)

# 默认设置(可被 store 中持久化的 settings 覆盖)
DEFAULTS = {
    # buffalo_l 的 normed_embedding 走余弦,经验阈值需实测校准
    "match_threshold": 0.40,
    # 活体
    "ear_threshold": 0.16,      # 低于判定闭眼(实测标定:睁眼中位~0.27,眨眼min~0.01)
    "ear_consec_frames": 2,     # 连续多少帧闭眼算一次有效闭合
    "yaw_threshold_deg": 45.0,  # 转头判定角度(实测标定:最大幅度~85°)
    "challenge_timeout_s": 6.0, # 单次活体挑战超时(从首次检测到人脸才开始计时)
    "no_face_timeout_s": 15.0,  # 一直检测不到人脸的总超时(防死循环)
    "required_blinks": 2,       # "眨眼"挑战需要的次数
    # 安全
    "renew_days": 90,           # 人脸到期重录天数
    # 录入
    "enroll_samples": 8,        # 录入采集合格帧数
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
