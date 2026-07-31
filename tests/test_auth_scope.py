from __future__ import annotations

import pytest

from face_hello import config
from face_hello.i18n import save_auth_scope_mirror
from face_hello.store import FaceStore


@pytest.mark.parametrize(
    ("enabled", "logon", "workstation", "expected"),
    [
        (True, True, True, "3"),
        (True, True, False, "1"),
        (True, False, True, "2"),
        (True, False, False, "0"),
        (False, True, True, "0"),
    ],
)
def test_save_auth_scope_mirror(tmp_path, monkeypatch, enabled, logon, workstation, expected):
    path = tmp_path / "auth_scope.txt"
    monkeypatch.setattr(config, "AVATAR_DIR", tmp_path)
    monkeypatch.setattr(config, "AUTH_SCOPE_FILE", path)

    save_auth_scope_mirror(enabled, logon, workstation)

    assert path.read_text(encoding="ascii") == expected


def test_auth_scope_defaults_preserve_existing_behavior(tmp_path):
    settings = FaceStore(tmp_path / "faces.dat").get_settings()

    assert settings["face_unlock_enabled"] is True
    assert settings["face_unlock_logon_enabled"] is True
    assert settings["face_unlock_workstation_enabled"] is True
