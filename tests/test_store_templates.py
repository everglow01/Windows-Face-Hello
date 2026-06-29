"""FaceStore 多模板录入:add_profile 覆盖/追加语义 + 每名 FIFO 上限。

纯逻辑、无 DPAPI:make_store 不落盘(不调 save/load),add_profile/embeddings 全内存。
"""
from __future__ import annotations

import numpy as np

from conftest import make_store, unit_vec


def _emb(tag: int) -> np.ndarray:
    """可区分的单位向量:第 tag 维置 1,用来核验留下/丢弃了哪条。"""
    return unit_vec(*([0] * tag + [1]))


def _names(store):
    return [p.name for p in store.list_profiles()]


def test_replace_default_overwrites_same_name(tmp_path):
    s = make_store(tmp_path)
    s.add_profile("owen", _emb(0))
    s.add_profile("owen", _emb(1))  # 默认 replace=True → 覆盖
    assert _names(s) == ["owen"]
    assert len(s.embeddings()) == 1
    assert np.allclose(s.embeddings()[0], _emb(1))


def test_append_keeps_same_name(tmp_path):
    s = make_store(tmp_path)
    s.add_profile("owen", _emb(0))
    s.add_profile("owen", _emb(1), replace=False)  # 追加
    assert _names(s) == ["owen", "owen"]
    assert len(s.embeddings()) == 2


def test_append_fifo_cap_drops_oldest(tmp_path):
    s = make_store(tmp_path, max_templates_per_name=3)
    for i in range(4):  # 追加 t0,t1,t2,t3 → 超上限丢最早 t0
        s.add_profile("owen", _emb(i), replace=False)
    embs = s.embeddings()
    assert len(embs) == 3
    # 留下的是最近 3 条(t1,t2,t3),最早的 t0 被丢
    kept = {int(np.argmax(e)) for e in embs}
    assert kept == {1, 2, 3}


def test_append_cap_per_name_independent(tmp_path):
    s = make_store(tmp_path, max_templates_per_name=2)
    for i in range(3):
        s.add_profile("owen", _emb(i), replace=False)
    s.add_profile("alice", _emb(7), replace=False)
    # owen 封顶 2,alice 不受影响
    assert sum(1 for n in _names(s) if n == "owen") == 2
    assert sum(1 for n in _names(s) if n == "alice") == 1


def test_remove_profile_drops_all_templates(tmp_path):
    s = make_store(tmp_path)
    s.add_profile("owen", _emb(0))
    s.add_profile("owen", _emb(1), replace=False)
    s.remove_profile("owen")
    assert s.is_empty()
