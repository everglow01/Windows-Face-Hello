"""运行时版本与严格稳定版版本解析。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_BUILD_INFO_PATH = Path(__file__).with_name("_build_info.json")
_STABLE_VERSION_RE = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")
_DEVELOPMENT_VERSION = "0.0.0-dev"


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class BuildInfo:
    version: str
    tag: str
    commit: str
    built_at: str

    @property
    def is_release(self) -> bool:
        try:
            parse_stable_version(self.version)
        except ValueError:
            return False
        return self.tag == f"v{self.version}"


def parse_stable_version(value: str) -> Version:
    """解析规范的 MAJOR.MINOR.PATCH；拒绝前导零和预发布后缀。"""
    match = _STABLE_VERSION_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid stable version: {value!r}")
    return Version(*(int(part) for part in match.groups()))


def _load_build_info(path: Path = _BUILD_INFO_PATH) -> BuildInfo:
    if not path.exists():
        return BuildInfo(_DEVELOPMENT_VERSION, "", "", "")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        info = BuildInfo(
            version=data["version"],
            tag=data["tag"],
            commit=data["commit"],
            built_at=data["built_at"],
        )
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError(f"invalid build info: {path}") from exc
    if not all(isinstance(value, str) for value in info.__dict__.values()):
        raise RuntimeError(f"invalid build info: {path}")
    if not info.is_release:
        raise RuntimeError(f"invalid release version in build info: {info.version!r}")
    return info


def get_build_info() -> BuildInfo:
    return _load_build_info()


def get_current_version() -> Version | None:
    """返回正式构建版本；源码开发态返回 None。"""
    info = get_build_info()
    if not info.is_release:
        return None
    return parse_stable_version(info.version)


def display_version() -> str:
    return get_build_info().version
