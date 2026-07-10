"""摄像头采集封装(OpenCV)。"""
from __future__ import annotations

import time
import threading

import cv2

from . import platform_backend

_capture_lock = threading.Lock()


class Camera:
    """普通 RGB 摄像头采集。Windows 下用 DSHOW 后端打开更快更稳。"""

    def __init__(self, index: int = 0):
        self.index = index
        self._cap: cv2.VideoCapture | None = None
        self._has_lock = False

    def open(self, timeout_s: float = 30.0, delay: float = 0.3) -> None:
        """打开摄像头并确认能取到一帧;DSHOW 后端在 timeout_s 内退避重试,超时才抛错。

        只用 DSHOW:MSMF 后端在设备不可用时,`VideoCapture()` 构造调用会阻塞数十分钟
        (实测一次卡了约 33min),且是 C++ 层阻塞、Python 超时打不断,故不能用作回退。
        每次尝试把 open/read/耗时打进日志,便于排查睡眠唤醒后 DSHOW 何时恢复。
        """
        if self._cap is not None:
            return
        if not _capture_lock.acquire(blocking=False):
            raise RuntimeError("摄像头正被另一个 FaceHello 操作使用")
        self._has_lock = True
        try:
            start = time.monotonic()
            attempt = 0
            while True:
                attempt += 1
                t0 = time.monotonic()
                cap = platform_backend.open_capture(self.index)
                opened = cap.isOpened()
                read_ok = False
                if opened:
                    ok, frame = cap.read()
                    read_ok = bool(ok and frame is not None)
                if read_ok:
                    print(f"[摄像头] DSHOW 第 {attempt} 次就绪,累计 {time.monotonic() - start:.1f}s",
                          flush=True)
                    self._cap = cap
                    return
                cap.release()
                print(f"[摄像头] DSHOW 第 {attempt} 次失败 open={opened} read={read_ok} "
                      f"本次 {time.monotonic() - t0:.1f}s", flush=True)
                if time.monotonic() - start >= timeout_s:
                    raise RuntimeError(
                        f"无法打开摄像头(index={self.index},{timeout_s:.0f}s 内 {attempt} 次均失败)"
                    )
                time.sleep(delay)
        except Exception:
            self.release()
            raise

    def read(self):
        """返回一帧 BGR 图;失败抛异常。"""
        if self._cap is None:
            raise RuntimeError("摄像头未打开,请先 open()")
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise RuntimeError("读取摄像头帧失败")
        return frame

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        if self._has_lock:
            self._has_lock = False
            _capture_lock.release()

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
