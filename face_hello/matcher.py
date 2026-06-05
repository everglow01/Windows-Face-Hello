"""特征比对:余弦相似度。

InsightFace 的 normed_embedding 已 L2 归一化,余弦相似度即点积。
"""
from __future__ import annotations

import numpy as np


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def best_match(probe: np.ndarray, gallery: list[np.ndarray]) -> tuple[int, float]:
    """返回 (最相似的索引, 相似度);gallery 为空返回 (-1, 0)。"""
    if not gallery:
        return -1, 0.0
    sims = [cosine_similarity(probe, g) for g in gallery]
    idx = int(np.argmax(sims))
    return idx, sims[idx]
