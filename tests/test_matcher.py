"""matcher.best_match_with_margin:多账户防错配的 margin 逻辑(红线:不把 A 解成 B)。"""
from __future__ import annotations

import math

import numpy as np

from conftest import unit_vec

from face_hello.matcher import best_match_with_margin, cosine_similarity


def test_empty_gallery():
    idx, sim, margin = best_match_with_margin(unit_vec(1), [], [])
    assert (idx, sim, margin) == (-1, 0.0, 0.0)


def test_single_profile_no_rival_margin_inf():
    # 只录一个人:无竞争者,margin = inf 表示无歧义
    gallery = [unit_vec(1)]
    idx, sim, margin = best_match_with_margin(unit_vec(1), gallery, ["alice"])
    assert idx == 0
    assert sim == 1.0
    assert margin == math.inf


def test_same_name_multi_template_not_rival():
    # 同一个人多模板(同名)不算竞争者,仍 inf
    gallery = [unit_vec(1, 0), unit_vec(0.9, 0.1)]
    idx, sim, margin = best_match_with_margin(unit_vec(1, 0), gallery, ["alice", "alice"])
    assert idx == 0
    assert margin == math.inf


def test_two_people_margin_is_best_minus_rival():
    # probe 贴近 alice;bob 正交 → margin = cos(probe,alice) - cos(probe,bob)
    alice, bob = unit_vec(1, 0), unit_vec(0, 1)
    probe = unit_vec(1, 0)
    idx, sim, margin = best_match_with_margin(probe, [alice, bob], ["alice", "bob"])
    assert idx == 0
    assert sim == 1.0
    assert margin == 1.0  # 1.0 - 0.0


def test_two_people_close_rival_small_margin():
    # bob 与 alice 贴得很近 → margin 很小(歧义,_recognize 应据此拒绝)
    alice, bob = unit_vec(1, 0), unit_vec(0.98, 0.2)
    probe = unit_vec(1, 0)
    idx, sim, margin = best_match_with_margin(probe, [alice, bob], ["alice", "bob"])
    assert idx == 0
    assert 0 < margin < 0.05
    # 与手算一致
    assert margin == sim - cosine_similarity(probe, bob)


def test_cosine_zero_vector_is_zero():
    assert cosine_similarity(np.zeros(4, dtype=np.float32), unit_vec(1)) == 0.0
