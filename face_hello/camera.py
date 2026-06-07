"""摄像头采集封装(OpenCV)。"""
from __future__ import annotations

import time

import cv2


class Camera:
    """普通 RGB 摄像头采集。Windows 下用 DSHOW 后端打开更快更稳。"""

    def __init__(self, index: int = 0):
        self.index = index
        self._cap: cv2.VideoCapture | None = None

    def open(self, retries: int = 8, delay: float = 0.5) -> None:
        """打开摄像头并确认能取到一帧。

        冷启动 / 睡眠唤醒后 USB 摄像头要几秒才枚举就绪——首次 open 常失败,或
        isOpened() 为真却读不出帧。带退避重试,直到真正能 read() 到一帧。
        """
        for _ in range(retries):
            cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
            if cap.isOpened():
                ok, _frame = cap.read()
                if ok and _frame is not None:
                    self._cap = cap
                    return
            cap.release()
            time.sleep(delay)
        raise RuntimeError(f"无法打开摄像头(index={self.index},已重试 {retries} 次)")

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

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
