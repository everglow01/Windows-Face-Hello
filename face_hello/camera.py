"""摄像头采集封装(OpenCV)。"""
from __future__ import annotations

import cv2


class Camera:
    """普通 RGB 摄像头采集。Windows 下用 DSHOW 后端打开更快更稳。"""

    def __init__(self, index: int = 0):
        self.index = index
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            raise RuntimeError(f"无法打开摄像头(index={self.index})")
        self._cap = cap

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
