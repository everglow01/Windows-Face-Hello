"""离线自检:不需要摄像头/显示器,验证核心链路。

运行:  uv run python scripts/offline_check.py
检查:模型加载、DPAPI 加密往返、matcher、FaceMesh 处理。
"""
from __future__ import annotations

import numpy as np

from face_hello import matcher
from face_hello.detector import FaceDetector
from face_hello.liveness import FaceMeshTracker
from face_hello.store import FaceStore


def check_matcher() -> None:
    a = np.array([1, 0, 0], dtype=np.float32)
    b = np.array([0, 1, 0], dtype=np.float32)
    assert abs(matcher.cosine_similarity(a, a) - 1.0) < 1e-6
    assert abs(matcher.cosine_similarity(a, b)) < 1e-6
    idx, sim = matcher.best_match(a, [b, a])
    assert idx == 1 and sim > 0.99
    # margin:单人无竞争者 → inf;probe 偏向 a 但离 b 不远 → margin 小
    _, _, m1 = matcher.best_match_with_margin(a, [a], ["alice"])
    assert m1 == float("inf")
    probe = np.array([1.0, 0.6, 0.0], dtype=np.float32)  # 既像 a 又有点像 b
    idx2, _, m2 = matcher.best_match_with_margin(probe, [a, b], ["alice", "bob"])
    assert idx2 == 0 and 0.0 < m2 < 0.5
    print("[ok] matcher 余弦相似度 + 多账户 margin")


def check_store(tmp_path) -> None:
    emb = np.random.RandomState(0).randn(512).astype(np.float32)
    s = FaceStore(path=tmp_path)
    s.add_profile("tester", emb, renew_days=90)
    s.update_settings(match_threshold=0.42)
    s.save()

    s2 = FaceStore(path=tmp_path).load()
    p = s2.list_profiles()[0]
    assert p.name == "tester"
    assert np.allclose(p.embedding, emb)
    assert s2.get_settings()["match_threshold"] == 0.42
    assert tmp_path.read_bytes()[:16] != emb.tobytes()[:16]  # 确认是密文,非明文
    print("[ok] store DPAPI 加密往返 + 设置持久化")


def check_facemesh() -> None:
    tracker = FaceMeshTracker()
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    assert tracker.process(blank) is None  # 空白图无人脸
    tracker.close()
    print("[ok] FaceMesh 处理(空白图返回 None)")


def check_detector() -> None:
    det = FaceDetector()
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    faces = det.detect(blank)  # 触发 buffalo_l 下载/加载
    assert faces == []
    print("[ok] InsightFace 模型加载 + 检测(空白图 0 张脸)")


def main() -> None:
    import tempfile
    from pathlib import Path

    check_matcher()
    check_facemesh()
    with tempfile.TemporaryDirectory() as d:
        check_store(Path(d) / "faces.dat")
    check_detector()
    print("\n[PASS] 全部离线自检通过")


if __name__ == "__main__":
    main()
