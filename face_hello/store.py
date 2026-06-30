"""人脸库:静态加密落盘。

存特征向量(非照片)+ 元数据(录入日期、renew_days)+ 设置。
加密走 `platform_backend`(Windows = DPAPI 机器范围:同机任意账户含 SYSTEM 服务可解、
换机不可解;存的是特征向量,机器范围暴露面可接受)。
"""
from __future__ import annotations

import datetime as _dt
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import config
from .platform_backend import protect as _protect, unprotect as _unprotect


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
    def add_profile(self, name: str, embedding: np.ndarray, renew_days: int | None = None,
                    replace: bool = True) -> None:
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
