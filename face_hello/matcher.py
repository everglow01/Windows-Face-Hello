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


def best_match_with_margin(
    probe: np.ndarray, gallery: list[np.ndarray], names: list[str]
) -> tuple[int, float, float]:
    """返回 (最相似索引, 相似度, margin)。

    margin = 最佳相似度 − 「最相似的另一个人(profile 名不同)」的相似度;只有一个 profile
    (无竞争者)时返回 inf,表示无歧义。多账户共用一个 gallery 时,用 margin 防错配——
    最佳与次佳贴得太近(<阈值)时应判为歧义、拒绝,而不是冒险解错账户。

    names[i] 为 gallery[i] 对应的 profile 名,跨档比较(同名多模板不算竞争者)。
    gallery 为空返回 (-1, 0.0, 0.0)。
    """
    if not gallery:
        return -1, 0.0, 0.0
    sims = [cosine_similarity(probe, g) for g in gallery]
    idx = int(np.argmax(sims))
    best = sims[idx]
    rivals = [s for i, s in enumerate(sims) if names[i] != names[idx]]
    margin = (best - max(rivals)) if rivals else float("inf")
    return idx, best, margin
