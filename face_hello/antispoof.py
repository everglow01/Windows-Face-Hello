"""被动反欺骗(RGB 活体):Silent-Face 单个 MiniFASNet,判屏幕翻拍 / 视频回放。

在识别那一帧上跑一次推理(见 auth.AuthSession._recognize),挡录好「眨眼+转头」
的视频回放——主动活体(眨眼/转头)挡不住这类攻击。

关键:MiniFASNet 对裁剪框极敏感,必须用它配套的 RetinaFace 检测框(实测用
InsightFace 的紧框会把真脸判成假)。因此本模块自带一个 RetinaFace(cv2.dnn caffe)
检测器,自己在整帧上找脸 → 按官方 scale=2.7 裁剪 → 喂 MiniFASNet。

模型 I/O(已实测对齐官方):
  - 检测:RetinaFace caffe,返回 [x, y, w, h]。
  - 分类输入:1×3×80×80 float32,BGR,**0~255 不归一化**,CHW
    (官方 ToTensor 把 .div(255) 注释掉了,return img.float())。
  - 输出:1×3 logits;softmax 后 index 1 = real。real ≥ 阈值 放行。
    (实测:真脸 real≈1.0,手机翻拍 real≈0.04,分得很开。)

fail-open:任一模型文件缺失 / 加载失败 / 某帧检测不到脸 → 返回 None,认证侧跳过
反欺骗、照常解锁(符合「绝不锁死用户、密码永远兜底」)。
"""
from __future__ import annotations

import logging
import threading

import cv2
import numpy as np

from . import config

_log = logging.getLogger("facehello")
_SCALE = 2.7      # MiniFASNetV2 2.7_80x80 的裁剪放大系数(配套训练值)
_SIZE = 80        # 模型输入边长
_DET_CONF = 0.6   # RetinaFace 置信度门槛,低于视作没检到脸


def _try_download(path, url) -> None:
    if path.exists() or not url:
        return
    try:
        import urllib.request

        config.ensure_dirs()
        urllib.request.urlretrieve(url, path)
    except Exception:  # noqa: BLE001 下载失败走 fail-open
        _log.warning("反欺骗文件下载失败:%s", path.name, exc_info=True)


def _files_ready() -> bool:
    _try_download(config.ANTISPOOF_MODEL, config.ANTISPOOF_MODEL_URL)
    _try_download(config.ANTISPOOF_DET_PROTO, config.ANTISPOOF_DET_PROTO_URL)
    _try_download(config.ANTISPOOF_DET_MODEL, config.ANTISPOOF_DET_MODEL_URL)
    return (
        config.ANTISPOOF_MODEL.exists()
        and config.ANTISPOOF_DET_PROTO.exists()
        and config.ANTISPOOF_DET_MODEL.exists()
    )


def _read_caffe(proto_path, model_path):
    """Unicode 路径安全地加载 caffe 网:OpenCV 在 Windows 读不了非 ASCII 路径,
    先把两个文件拷到临时 ASCII 目录再 readNetFromCaffe(同仓库 OpenCV 中文路径坑)。"""
    import os
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "deploy.prototxt")
        m = os.path.join(d, "model.caffemodel")
        shutil.copyfile(proto_path, p)
        shutil.copyfile(model_path, m)
        return cv2.dnn.readNetFromCaffe(p, m)


def _get_new_box(src_w, src_h, bbox, scale):
    """port 自 Silent-Face CropImage._get_new_box(逐行对齐)。bbox = [x, y, w, h]。"""
    x, y, box_w, box_h = bbox[0], bbox[1], max(1, bbox[2]), max(1, bbox[3])
    scale = min((src_h - 1) / box_h, min((src_w - 1) / box_w, scale))
    new_w = box_w * scale
    new_h = box_h * scale
    cx, cy = box_w / 2 + x, box_h / 2 + y
    lt_x = cx - new_w / 2
    lt_y = cy - new_h / 2
    rb_x = cx + new_w / 2
    rb_y = cy + new_h / 2
    if lt_x < 0:
        rb_x -= lt_x
        lt_x = 0
    if lt_y < 0:
        rb_y -= lt_y
        lt_y = 0
    if rb_x > src_w - 1:
        lt_x -= rb_x - src_w + 1
        rb_x = src_w - 1
    if rb_y > src_h - 1:
        lt_y -= rb_y - src_h + 1
        rb_y = src_h - 1
    return int(lt_x), int(lt_y), int(rb_x), int(rb_y)


class AntiSpoofModel:
    """RetinaFace 检测 + 单个 MiniFASNet 分类。score() 返回 real 概率(0..1)或 None。"""

    def __init__(self):
        import math

        import onnxruntime as ort

        self._math = math
        self._sess = ort.InferenceSession(
            str(config.ANTISPOOF_MODEL), providers=["CPUExecutionProvider"]
        )
        self._input = self._sess.get_inputs()[0].name
        self._det = _read_caffe(config.ANTISPOOF_DET_PROTO, config.ANTISPOOF_DET_MODEL)

    def _bbox(self, frame_bgr):
        """RetinaFace 取最高分人脸框 [x, y, w, h];置信度过低返回 None。"""
        h, w = frame_bgr.shape[:2]
        img = frame_bgr
        if w * h >= 192 * 192:  # 官方:大图先缩到 ~192 长边再检测,坐标按原图还原
            ar = w / h
            img = cv2.resize(img, (int(192 * self._math.sqrt(ar)),
                                   int(192 / self._math.sqrt(ar))))
        blob = cv2.dnn.blobFromImage(img, 1, mean=(104, 117, 123))
        self._det.setInput(blob, "data")
        out = self._det.forward("detection_out").squeeze()
        i = int(np.argmax(out[:, 2]))
        if float(out[i, 2]) < _DET_CONF:
            return None
        left, top = out[i, 3] * w, out[i, 4] * h
        right, bottom = out[i, 5] * w, out[i, 6] * h
        return [int(left), int(top), int(right - left + 1), int(bottom - top + 1)]

    def score(self, frame_bgr) -> float | None:
        bbox = self._bbox(frame_bgr)
        if bbox is None:
            return None
        h, w = frame_bgr.shape[:2]
        x1, y1, x2, y2 = _get_new_box(w, h, bbox, _SCALE)
        crop = cv2.resize(frame_bgr[y1:y2 + 1, x1:x2 + 1], (_SIZE, _SIZE))
        # 官方 ToTensor 把 /255 注释掉了(return img.float()),模型吃 0~255 的 BGR,别归一化
        blob = crop.astype(np.float32).transpose(2, 0, 1)[np.newaxis, ...]
        out = self._sess.run(None, {self._input: blob})[0]
        logits = np.asarray(out, dtype=np.float64).reshape(-1)
        e = np.exp(logits - logits.max())
        prob = e / e.sum()
        return float(prob[1])  # index 1 = real

    def load(self) -> None:
        """640×480 零图预热,首帧不卡(检测不到脸也无妨)。"""
        try:
            self.score(np.zeros((480, 640, 3), dtype=np.uint8))
        except Exception:  # noqa: BLE001 预热失败不致命
            pass


_instance: AntiSpoofModel | None = None
_load_failed = False
_lock = threading.Lock()


def get_antispoof() -> AntiSpoofModel | None:
    """懒加载单例。文件缺失 / 加载失败返回 None(fail-open),不再重试。"""
    global _instance, _load_failed
    if _instance is not None:
        return _instance
    if _load_failed:
        return None
    with _lock:
        if _instance is not None:
            return _instance
        if _load_failed:
            return None
        if not _files_ready():
            _log.warning("反欺骗模型文件不全(需 onnx + 检测器),跳过反欺骗(fail-open)")
            _load_failed = True
            return None
        try:
            _instance = AntiSpoofModel()
        except Exception:  # noqa: BLE001 加载失败 fail-open
            _log.warning("反欺骗模型加载失败,跳过反欺骗(fail-open)", exc_info=True)
            _load_failed = True
            return None
        return _instance
