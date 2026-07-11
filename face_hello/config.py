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
# 界面语言镜像:settings['language'] 的明文副本,供 C++ CP(SYSTEM)在锁屏读取
# (CP 读不了 DPAPI 加密的人脸库)。控制台改语言时写,服务启动时按 settings 同步。
LANG_FILE = _PROGRAMDATA / "lang.txt"
HOTKEY_FILE = _PROGRAMDATA / "hotkey.txt"

# 认证服务的命名管道(Credential Provider 通过它请求认证)
PIPE_NAME = r"\\.\pipe\FaceHello"
SERVICE_NAME = "FaceHello"

# 识别模型
INSIGHTFACE_MODEL = "buffalo_l"
DET_SIZE = (320, 320)  # 贴脸的摄像头 320 足够,比 640 快得多
INSIGHTFACE_DETECTION_MODEL = MODELS_DIR / INSIGHTFACE_MODEL / "det_10g.onnx"
INSIGHTFACE_RECOGNITION_MODEL = MODELS_DIR / INSIGHTFACE_MODEL / "w600k_r50.onnx"
TEMPLATE_LABEL_MAX_LENGTH = 24

# 活体用的 MediaPipe FaceLandmarker 模型(Tasks API,首次自动下载)
FACE_LANDMARKER = MODELS_DIR / "face_landmarker.task"
FACE_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)

# 被动反欺骗(Silent-Face MiniFASNet 2.7_80x80)。三个文件:分类 onnx + RetinaFace 检测器
# (prototxt + caffemodel)。MiniFASNet 对裁剪框极敏感,必须用配套的 RetinaFace 框,
# 不能用 InsightFace 的框(实测会判错),故单独带这个检测器。
# 任一文件缺失/加载失败 → 认证侧 fail-open(跳过反欺骗,照常解锁,见 antispoof.py)。
# URL 留空则不自动下载;自备文件放 models/ 或托管到 Release 后填直链。
ANTISPOOF_MODEL = MODELS_DIR / "antispoof.onnx"
ANTISPOOF_MODEL_URL = ""
ANTISPOOF_DET_PROTO = MODELS_DIR / "antispoof_detector.prototxt"
ANTISPOOF_DET_MODEL = MODELS_DIR / "antispoof_detector.caffemodel"
ANTISPOOF_DET_PROTO_URL = ""
ANTISPOOF_DET_MODEL_URL = ""

# 默认设置(可被 store 中持久化的 settings 覆盖)
DEFAULTS = {
    # 界面语言:"zh" / "en"。控制台、活体提示、锁屏磁贴共用同一值(见 i18n.py)。
    "language": "zh",
    # buffalo_l 的 normed_embedding 走余弦,经验阈值需实测校准
    "match_threshold": 0.40,
    # 多账户防错配:最佳与「最相似的另一个人」相似度差需 ≥ 此值才算确定身份,
    # 否则判为歧义、拒绝(避免把 A 解成 B)。只录一个人时不触发。0 = 关闭 margin 校验。
    "match_margin": 0.05,
    # 活体
    "liveness_enabled": True,   # 关掉则跳过活体直接识别(测试/低安全模式;牺牲防照片能力)
    "ear_threshold": 0.16,      # 低于判定闭眼(实测标定:睁眼中位~0.27,眨眼min~0.01)
    "ear_consec_frames": 2,     # 连续多少帧闭眼算一次有效闭合
    "yaw_threshold_deg": 45.0,  # 转头判定角度(实测标定:最大幅度~85°)
    "challenge_timeout_s": 6.0, # 单次活体挑战超时(从首次检测到人脸才开始计时)
    "no_face_timeout_s": 15.0,  # 一直检测不到人脸的总超时(防死循环)
    "required_blinks": 2,       # "眨眼"挑战需要的次数
    # 安全
    "renew_days": 90,           # 建议重新录入人脸的提醒周期
    # 失败锁定(只对真生物特征拒绝计数,基础设施错误不计):连续 N 次后冷却 T 秒,
    # 期间 auth_start 直接拒并提示走密码;成功或冷却到期清零。N=0 关闭锁定。
    "lockout_max_fails": 5,
    "lockout_seconds": 30,
    # 录入
    "enroll_samples": 8,        # 录入采集合格帧数
    "max_templates_per_name": 5,  # 每个用户最多存几条模板(补录角度),超出按 FIFO 丢最早
    # 摄像头索引(0=默认/第一个)。多摄像头(内置+USB+虚拟)时改这里;控制台「测试」按钮可预览确认。
    "camera_index": 0,
    "unlock_hotkey": "",
    # 被动反欺骗(RGB 活体):识别帧上跑一次 MiniFASNet 判屏幕翻拍/视频回放。
    # 模型缺失/加载失败则 fail-open(跳过,照常解锁)。默认开,安全优先。
    "antispoof_enabled": True,
    # real 概率阈值,低于判翻拍而拒绝(可被 settings 覆盖;UI 暂不暴露,留作后续标定)。
    "antispoof_threshold": 0.55,
    # 反欺骗最多采样帧数:某帧 RetinaFace 没检到脸(score=None)不立刻放行,继续采样直到
    # 拿到判真/判假定论;连续 N 帧都检测不到才 fail-open(堵住单帧漏检就跳过反欺骗的空子)。
    "antispoof_max_frames": 10,
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
