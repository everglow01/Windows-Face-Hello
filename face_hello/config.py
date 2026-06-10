"""集中配置:路径、模型、阈值。

非敏感运行参数(阈值/renew_days 等)可被 store 中的 settings 覆盖;
敏感数据(人脸特征)由 store.py 走 DPAPI 加密单独存放。
"""
from __future__ import annotations

import os
from pathlib import Path

# 项目根:face_hello/config.py -> 上两级(开发态用)
ROOT = Path(__file__).resolve().parents[1]

# 安装态 / 开发态分流:安装器写环境变量 FACEHELLO_HOME=<安装根>(如 C:\Program Files\FaceHello);
# 开发态没有该变量,一切走仓库相对路径,uv run 流程完全不变。
#   - 程序文件(模型、CP DLL):安装态在只读安装目录,开发态在仓库
#   - 可写数据(人脸库、日志):安装态固定落 ProgramData(SYSTEM 服务 + 提权 GUI 共享),开发态在仓库 data/
_HOME = os.environ.get("FACEHELLO_HOME")
_PROGRAMDATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "FaceHello"
# 安装器在安装根放一个空的 .installed 标记文件作为安装态依据。优先它(而非只靠
# FACEHELLO_HOME 环境变量)是因为 SCM 把系统环境变量块缓存到下次重启,SYSTEM 服务
# 装好当下读不到新设的 FACEHELLO_HOME;标记文件随安装即落盘,服务 / GUI 立刻一致,
# 无需重启。FACEHELLO_HOME 仍兼容(开发 / 调试显式指定安装根)。
_MARKER = ROOT / ".installed"
IS_INSTALLED = bool(_HOME) or _MARKER.exists()

if IS_INSTALLED:  # 安装态
    INSTALL_ROOT = Path(_HOME) if _HOME else ROOT
    DATA_DIR = _PROGRAMDATA / "data"
    MODELS_DIR = INSTALL_ROOT / "models"
    CP_DLL = INSTALL_ROOT / "FaceHelloCP.dll"  # 安装布局:DLL 在安装根(DESIGN 10.2)
else:             # 开发态
    INSTALL_ROOT = ROOT
    DATA_DIR = ROOT / "data"
    MODELS_DIR = ROOT / "models"
    CP_DLL = ROOT / "cp" / "x64" / "Release" / "FaceHelloCP.dll"  # MSBuild 产物

FACE_STORE = DATA_DIR / "faces.dat"  # DPAPI 加密的人脸库
# 锁屏磁贴自定义头像目录(两态一致;CP 硬编码读 C:\ProgramData\FaceHello\,SYSTEM 可读、纯 ASCII)。
AVATAR_DIR = _PROGRAMDATA

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
    "liveness_enabled": True,   # 关掉则跳过活体直接识别(测试/低安全模式;牺牲防照片能力)
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
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
