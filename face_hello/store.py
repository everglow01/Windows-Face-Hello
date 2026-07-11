"""人脸库:静态加密落盘。

存特征向量(非照片)+ 元数据(录入日期、renew_days)+ 设置。
加密走 `platform_backend`(Windows = DPAPI 机器范围:同机任意账户含 SYSTEM 服务可解、
换机不可解;存的是特征向量,机器范围暴露面可接受)。
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import math
import os
import pickle
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import config
from .platform_backend import protect as _protect, unprotect as _unprotect

_FORMAT_MAGIC = b"FACEHELLO2\n"
_MAX_STORE_BYTES = 16 * 1024 * 1024
_MAX_PROFILES = 1000
_EMBEDDING_SIZE = 512

_LEGACY_GLOBALS = {
    ("datetime", "date"): _dt.date,
    ("numpy", "dtype"): np.dtype,
    ("numpy", "ndarray"): np.ndarray,
    ("numpy.core.multiarray", "_reconstruct"): np.core.multiarray._reconstruct,
    ("numpy._core.multiarray", "_reconstruct"): np.core.multiarray._reconstruct,
    ("numpy.core.multiarray", "scalar"): np.core.multiarray.scalar,
    ("numpy._core.multiarray", "scalar"): np.core.multiarray.scalar,
}


def _clean_label(label: str) -> str:
    return str(label or "").strip()[:config.TEMPLATE_LABEL_MAX_LENGTH]


class _LegacyUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        allowed = _LEGACY_GLOBALS.get((module, name))
        if allowed is None:
            raise pickle.UnpicklingError(f"unsupported legacy type: {module}.{name}")
        return allowed


def _valid_setting(key: str, value) -> bool:
    if key not in config.DEFAULTS:
        return False
    default = config.DEFAULTS[key]
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(default, float):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    return isinstance(value, type(default))


def _normalize_data(data) -> dict:
    if not isinstance(data, dict):
        raise ValueError("invalid face store root")
    settings = data.get("settings", {})
    profiles = data.get("profiles", [])
    if not isinstance(settings, dict) or not isinstance(profiles, list):
        raise ValueError("invalid face store structure")
    if len(profiles) > _MAX_PROFILES:
        raise ValueError("too many face profiles")

    clean_settings = {
        key: value for key, value in settings.items()
        if isinstance(key, str) and _valid_setting(key, value)
    }
    clean_profiles = []
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError("invalid face profile")
        name = profile.get("name")
        if not isinstance(name, str) or not name or len(name) > 256 or "\0" in name:
            raise ValueError("invalid profile name")
        raw_embedding = profile.get("embedding")
        embedding = np.asarray(raw_embedding)
        if embedding.dtype.kind not in "fiu" or embedding.shape != (_EMBEDDING_SIZE,):
            raise ValueError("invalid face embedding")
        embedding = embedding.astype(np.float32, copy=False)
        if not np.isfinite(embedding).all():
            raise ValueError("invalid face embedding values")
        enroll_date = profile.get("enroll_date")
        if isinstance(enroll_date, str):
            enroll_date = _dt.date.fromisoformat(enroll_date)
        if not isinstance(enroll_date, _dt.date):
            raise ValueError("invalid enrollment date")
        renew_days = profile.get("renew_days")
        if (
            not isinstance(renew_days, int)
            or isinstance(renew_days, bool)
            or not 1 <= renew_days <= 36500
        ):
            raise ValueError("invalid renewal period")
        label = profile.get("label", "")
        if not isinstance(label, str):
            raise ValueError("invalid profile label")
        clean_profiles.append(
            {
                "name": name,
                "embedding": embedding,
                "enroll_date": enroll_date,
                "renew_days": renew_days,
                "label": _clean_label(label),
            }
        )
    return {"settings": clean_settings, "profiles": clean_profiles}


def _encode_data(data: dict) -> bytes:
    normalized = _normalize_data(data)
    serializable = {
        "schema_version": 2,
        "settings": normalized["settings"],
        "profiles": [
            {
                **profile,
                "embedding": profile["embedding"].tolist(),
                "enroll_date": profile["enroll_date"].isoformat(),
            }
            for profile in normalized["profiles"]
        ],
    }
    payload = json.dumps(
        serializable, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    return _FORMAT_MAGIC + payload


def _decode_data(raw: bytes) -> dict:
    if raw.startswith(_FORMAT_MAGIC):
        data = json.loads(raw[len(_FORMAT_MAGIC):].decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("invalid face store root")
        if data.get("schema_version") != 2:
            raise ValueError("unsupported face store version")
    else:
        data = _LegacyUnpickler(io.BytesIO(raw)).load()
    return _normalize_data(data)


@dataclass
class Profile:
    name: str
    embedding: np.ndarray
    enroll_date: _dt.date
    renewal_interval_days: int
    label: str = ""

    @property
    def recommended_renewal_date(self) -> _dt.date:
        return self.enroll_date + _dt.timedelta(days=self.renewal_interval_days)

    @property
    def renewal_due(self) -> bool:
        return _dt.date.today() > self.recommended_renewal_date

    @property
    def days_until_renewal(self) -> int:
        return (self.recommended_renewal_date - _dt.date.today()).days


class FaceStore:
    """加密人脸库的读写。结构:{'settings': {...}, 'profiles': [dict, ...]}。"""

    def __init__(self, path: Path = config.FACE_STORE):
        self.path = path
        self._data: dict = {"settings": {}, "profiles": []}

    # ---- 持久化 ----
    def load(self) -> "FaceStore":
        if self.path.exists():
            blob = self.path.read_bytes()
            if len(blob) > _MAX_STORE_BYTES:
                raise ValueError("face store is too large")
            self._data = _decode_data(_unprotect(blob))
        return self

    def save(self) -> None:
        config.ensure_dirs()
        blob = _protect(_encode_data(self._data))
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        finally:
            if tmp.exists():
                tmp.unlink()

    # ---- 设置 ----
    def get_settings(self) -> dict:
        """DEFAULTS 叠加已持久化的覆盖项。"""
        merged = dict(config.DEFAULTS)
        merged.update(self._data.get("settings", {}))
        return merged

    def update_settings(self, **kw) -> None:
        self._data.setdefault("settings", {}).update(kw)

    # ---- 人脸 ----
    def add_profile(self, name: str, embedding: np.ndarray, renew_days: int | None = None,
                    replace: bool = True, label: str = "") -> None:
        """replace=True(默认):同名覆盖(重新录入 / 定期换脸)。
        replace=False:同名追加一条模板(补录角度),超过 max_templates_per_name 按 FIFO 丢最早。"""
        if renew_days is None:
            renew_days = self.get_settings()["renew_days"]
        if replace:
            self._data["profiles"] = [p for p in self._data["profiles"] if p["name"] != name]
        self._data["profiles"].append(
            {
                "name": name,
                "embedding": np.asarray(embedding, dtype=np.float32),
                "enroll_date": _dt.date.today(),
                "renew_days": int(renew_days),
                "label": _clean_label(label),
            }
        )
        if not replace:
            self._enforce_template_cap(name)

    def _enforce_template_cap(self, name: str) -> None:
        """同名模板数超上限时,按出现顺序丢最早的若干条(profiles 是时间序,先出现=最早)。"""
        cap = self.get_settings()["max_templates_per_name"]
        drop = sum(1 for p in self._data["profiles"] if p["name"] == name) - cap
        if drop <= 0:
            return
        kept: list[dict] = []
        for p in self._data["profiles"]:
            if p["name"] == name and drop > 0:
                drop -= 1  # 丢掉这条(最早的)
                continue
            kept.append(p)
        self._data["profiles"] = kept

    def remove_profile(self, name: str) -> None:
        self._data["profiles"] = [p for p in self._data["profiles"] if p["name"] != name]

    def remove_template(self, name: str, index: int) -> None:
        """删除该 name 下第 index 条模板(0-based,按录入顺序)。越界则 no-op。

        删到该名最后一条 → 该用户自然从库中消失(等同未录入)。
        """
        positions = [i for i, p in enumerate(self._data["profiles"]) if p["name"] == name]
        if 0 <= index < len(positions):
            del self._data["profiles"][positions[index]]

    def set_template_label(self, name: str, index: int, label: str) -> None:
        """设置该 name 下第 index 条模板的管理标签。越界则 no-op。"""
        positions = [i for i, p in enumerate(self._data["profiles"]) if p["name"] == name]
        if 0 <= index < len(positions):
            self._data["profiles"][positions[index]]["label"] = _clean_label(label)

    def list_profiles(self) -> list[Profile]:
        return [
            Profile(
                name=p["name"],
                embedding=p["embedding"],
                enroll_date=p["enroll_date"],
                renewal_interval_days=p["renew_days"],
                label=_clean_label(p.get("label", "")),
            )
            for p in self._data["profiles"]
        ]

    def embeddings(self) -> list[np.ndarray]:
        return [p["embedding"] for p in self._data["profiles"]]

    def is_empty(self) -> bool:
        return not self._data["profiles"]
