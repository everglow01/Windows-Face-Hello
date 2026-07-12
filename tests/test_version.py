from __future__ import annotations

import json

import pytest

from face_hello.version import (
    BuildInfo,
    Version,
    _load_build_info,
    parse_stable_version,
)


def test_parse_stable_version_and_compare():
    assert parse_stable_version("1.10.0") > parse_stable_version("1.9.0")
    assert parse_stable_version("1.2.3") == Version(1, 2, 3)
    assert str(Version(1, 2, 3)) == "1.2.3"


@pytest.mark.parametrize(
    "value",
    ["v1.2.3", "1.2", "1.2.3-beta", "01.2.3", "1.02.3", "1.2.03", " 1.2.3"],
)
def test_parse_stable_version_rejects_noncanonical_values(value):
    with pytest.raises(ValueError):
        parse_stable_version(value)


def test_missing_build_info_is_development(tmp_path):
    info = _load_build_info(tmp_path / "missing.json")
    assert info.version == "0.0.0-dev"
    assert not info.is_release


def test_load_release_build_info(tmp_path):
    path = tmp_path / "build.json"
    path.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "tag": "v1.2.3",
                "commit": "a" * 40,
                "built_at": "2026-07-12T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    assert _load_build_info(path) == BuildInfo(
        "1.2.3", "v1.2.3", "a" * 40, "2026-07-12T00:00:00Z"
    )


def test_load_build_info_rejects_tag_mismatch(tmp_path):
    path = tmp_path / "build.json"
    path.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "tag": "v1.2.4",
                "commit": "a" * 40,
                "built_at": "2026-07-12T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError):
        _load_build_info(path)
