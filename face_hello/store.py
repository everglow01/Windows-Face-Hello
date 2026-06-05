"""人脸库:DPAPI 加密落盘。

存特征向量(非照片)+ 元数据(录入日期、renew_days)+ 设置。
用 Windows DPAPI(win32crypt)按当前用户加密,换用户/换机无法解密。
"""
from __future__ import annotations

import datetime as _dt
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import config

_ENTROPY = b"face_hello_v1"  # 附加熵,降低跨程序解密风险


def _protect(raw: bytes) -> bytes:
    import win32crypt

    return win32crypt.CryptProtectData(raw, "face_hello", _ENTROPY, None, None, 0)


def _unprotect(blob: bytes) -> bytes:
    import win32crypt

    _desc, raw = win32crypt.CryptUnprotectData(blob, _ENTROPY, None, None, 0)
    return raw


@dataclass
class Profile:
    name: str
    embedding: np.ndarray
    enroll_date: _dt.date
    renew_days: int

    @property
    def expire_date(self) -> _dt.date:
        return self.enroll_date + _dt.timedelta(days=self.renew_days)

    @property
    def is_expired(self) -> bool:
        return _dt.date.today() > self.expire_date

    @property
    def days_left(self) -> int:
        return (self.expire_date - _dt.date.today()).days


class FaceStore:
    """加密人脸库的读写。结构:{'settings': {...}, 'profiles': [dict, ...]}。"""

    def __init__(self, path: Path = config.FACE_STORE):
        self.path = path
        self._data: dict = {"settings": {}, "profiles": []}

    # ---- 持久化 ----
    def load(self) -> "FaceStore":
        if self.path.exists():
            self._data = pickle.loads(_unprotect(self.path.read_bytes()))
        return self

    def save(self) -> None:
        config.ensure_dirs()
        self.path.write_bytes(_protect(pickle.dumps(self._data)))

    # ---- 设置 ----
    def get_settings(self) -> dict:
        """DEFAULTS 叠加已持久化的覆盖项。"""
        merged = dict(config.DEFAULTS)
        merged.update(self._data.get("settings", {}))
        return merged

    def update_settings(self, **kw) -> None:
        self._data.setdefault("settings", {}).update(kw)

    # ---- 人脸 ----
    def add_profile(self, name: str, embedding: np.ndarray, renew_days: int | None = None) -> None:
        if renew_days is None:
            renew_days = self.get_settings()["renew_days"]
        # 同名覆盖(重新录入 / 定期换脸)
        self._data["profiles"] = [p for p in self._data["profiles"] if p["name"] != name]
        self._data["profiles"].append(
            {
                "name": name,
                "embedding": np.asarray(embedding, dtype=np.float32),
                "enroll_date": _dt.date.today(),
                "renew_days": int(renew_days),
            }
        )

    def remove_profile(self, name: str) -> None:
        self._data["profiles"] = [p for p in self._data["profiles"] if p["name"] != name]

    def list_profiles(self) -> list[Profile]:
        return [
            Profile(
                name=p["name"],
                embedding=p["embedding"],
                enroll_date=p["enroll_date"],
                renew_days=p["renew_days"],
            )
            for p in self._data["profiles"]
        ]

    def embeddings(self) -> list[np.ndarray]:
        return [p["embedding"] for p in self._data["profiles"]]

    def is_empty(self) -> bool:
        return not self._data["profiles"]
