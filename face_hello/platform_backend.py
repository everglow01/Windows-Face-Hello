"""平台后端:把 OS 相关的三件事收敛到一处 —— 数据静态加密、摄像头后端选择、当前用户名。

阶段 6(跨平台)的第一步:这之前 DPAPI / `CAP_DSHOW` / `GetUserName()` 散落在
`store.py`/`camera.py`/`cred_vault.py`。收敛后,将来移植 Linux(PAM)/ macOS 只需在此
补对应实现,核心识别管线无须改动。

Windows 行为与重构前**逐字节一致**(DPAPI 机器范围 / DSHOW / GetUserName),
现有 `faces.dat` 仍可正常解密。

非 Windows:摄像头与用户名给出可用的默认实现(便于在 Linux/Mac 上开发、跑离线自检);
**数据加密留 `NotImplementedError`** —— Linux/Mac 的静态加密方案(root 私有文件 0600 /
Keychain / libsecret)是阶段 6 要正式拍板的安全决策,不在此处臆测。
"""
from __future__ import annotations

import sys

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# ---- 数据静态加密(人脸库落盘加密)----
# Windows = DPAPI 机器范围:同机任意账户(含 SYSTEM 服务)可解,换机不可解。
_DPAPI_ENTROPY = b"face_hello_v1"      # 附加熵,降低跨程序解密风险
_DPAPI_LOCAL_MACHINE = 0x4             # CRYPTPROTECT_LOCAL_MACHINE:机器范围,SYSTEM 服务才解得开录入用户写的库


def protect(raw: bytes) -> bytes:
    """加密落盘前的字节。"""
    if IS_WINDOWS:
        import win32crypt

        return win32crypt.CryptProtectData(
            raw, "face_hello", _DPAPI_ENTROPY, None, None, _DPAPI_LOCAL_MACHINE
        )
    raise NotImplementedError(
        "非 Windows 的人脸库静态加密尚未实现(阶段 6:Linux=root 私有文件 / macOS=Keychain)"
    )


def unprotect(blob: bytes) -> bytes:
    """解密读出的字节。"""
    if IS_WINDOWS:
        import win32crypt

        _desc, raw = win32crypt.CryptUnprotectData(blob, _DPAPI_ENTROPY, None, None, 0)
        return raw
    raise NotImplementedError(
        "非 Windows 的人脸库静态加密尚未实现(阶段 6:Linux=root 私有文件 / macOS=Keychain)"
    )


# ---- 摄像头后端 ----
def open_capture(index: int):
    """按平台选 OpenCV 后端打开摄像头,返回 `cv2.VideoCapture`。

    Windows 固定 DSHOW(MSMF 在设备不可用时会 C++ 层阻塞数十分钟,Python 超时打不断,
    详见 camera.py)。其余平台用默认后端(Linux=V4L2 / macOS=AVFoundation)。
    """
    import cv2

    if IS_WINDOWS:
        return cv2.VideoCapture(index, cv2.CAP_DSHOW)
    return cv2.VideoCapture(index)


# ---- 当前用户名 ----
def current_user() -> str:
    """当前账户名。Windows 返回 SAM 名(身份契约要求,见 cred_vault.py);其余平台用登录名。"""
    if IS_WINDOWS:
        import win32api

        return win32api.GetUserName()
    import getpass

    return getpass.getuser()
