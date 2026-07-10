from __future__ import annotations

import datetime as dt
import pickle

import numpy as np
import pytest

import face_hello.store as store_module
from face_hello.store import FaceStore


@pytest.fixture(autouse=True)
def _plain_storage(monkeypatch):
    monkeypatch.setattr(store_module, "_protect", lambda data: data)
    monkeypatch.setattr(store_module, "_unprotect", lambda data: data)


def _embedding() -> np.ndarray:
    result = np.zeros(512, dtype=np.float32)
    result[0] = 1.0
    return result


def test_versioned_store_roundtrip(tmp_path):
    path = tmp_path / "faces.dat"
    store = FaceStore(path)
    store.add_profile("owen", _embedding(), label="front")
    store.update_settings(match_threshold=0.45)
    store.save()

    assert path.read_bytes().startswith(store_module._FORMAT_MAGIC)
    loaded = FaceStore(path).load()
    assert loaded.list_profiles()[0].label == "front"
    assert np.allclose(loaded.embeddings()[0], _embedding())
    assert loaded.get_settings()["match_threshold"] == 0.45


def test_restricted_legacy_store_migrates_on_save(tmp_path):
    path = tmp_path / "faces.dat"
    legacy = {
        "settings": {"match_threshold": 0.42},
        "profiles": [{
            "name": "owen",
            "embedding": _embedding(),
            "enroll_date": dt.date.today(),
            "renew_days": 90,
        }],
    }
    path.write_bytes(pickle.dumps(legacy))

    store = FaceStore(path).load()
    assert store.list_profiles()[0].label == ""
    store.save()
    assert path.read_bytes().startswith(store_module._FORMAT_MAGIC)


def test_legacy_pickle_rejects_unapproved_globals(tmp_path):
    class Payload:
        def __reduce__(self):
            return eval, ("1 + 1",)

    path = tmp_path / "faces.dat"
    path.write_bytes(pickle.dumps(Payload()))
    with pytest.raises(pickle.UnpicklingError):
        FaceStore(path).load()


def test_failed_replace_preserves_existing_store(tmp_path, monkeypatch):
    path = tmp_path / "faces.dat"
    store = FaceStore(path)
    store.add_profile("owen", _embedding())
    store.save()
    original = path.read_bytes()
    store.update_settings(match_threshold=0.61)

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(store_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        store.save()
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".faces.dat.*.tmp"))
