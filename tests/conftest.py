"""安全逻辑 pytest 的共享工具。

这些测试只验证决策状态机(锁定 / margin 防错配 / 反欺骗门),全程不碰摄像头、
真模型、DPAPI:用合成的 L2 归一化向量、fake detector、未落盘的内存 FaceStore。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from face_hello.store import FaceStore

# buffalo_l 的 embedding 是 512 维;实际维度不影响余弦,固定一个即可。
DIM = 512


def unit_vec(*coords: float) -> np.ndarray:
    """前几维取 coords、其余补 0,再 L2 归一化(模拟 normed_embedding)。"""
    v = np.zeros(DIM, dtype=np.float32)
    v[: len(coords)] = coords
    n = np.linalg.norm(v)
    return v / n if n else v


@dataclass
class FakeFace:
    """detector.largest_face 的最小替身:_recognize 只读 .embedding(.bbox 备用)。"""

    embedding: np.ndarray
    bbox: tuple = (0, 0, 10, 10)


@dataclass
class FakeDetector:
    """largest_face 返回预设的 face(或 None 模拟没检到脸)。"""

    face: FakeFace | None = None
    calls: int = field(default=0)

    def largest_face(self, frame_bgr):
        self.calls += 1
        return self.face


def make_store(tmp_path, **settings) -> FaceStore:
    """未落盘的内存 FaceStore:用不存在的临时路径,load() 对缺失文件是 no-op,
    既不会触 DPAPI、也不会读到真人脸库。settings 覆盖 DEFAULTS。"""
    store = FaceStore(path=tmp_path / "faces.dat")
    if settings:
        store.update_settings(**settings)
    return store
