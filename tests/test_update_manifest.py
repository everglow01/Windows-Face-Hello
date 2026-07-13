from __future__ import annotations

import hashlib

import pytest

from face_hello.updater import parse_manifest
from scripts.generate_update_manifest import generate_manifest, write_release_metadata


def test_generate_release_metadata_round_trip(tmp_path):
    payload = b"signed installer placeholder"
    installer = tmp_path / "FaceHello-Setup-1.2.3.exe"
    installer.write_bytes(payload)

    write_release_metadata(installer, "1.2.3", "a" * 40, tmp_path)

    manifest_path = tmp_path / "facehello-update.json"
    parsed = parse_manifest(manifest_path.read_bytes())
    assert str(parsed.version) == "1.2.3"
    assert parsed.installer_size == len(payload)
    digest = hashlib.sha256(payload).hexdigest()
    assert parsed.installer_sha256 == digest
    assert (tmp_path / f"{installer.name}.sha256").read_text(encoding="ascii") == (
        f"{digest}  {installer.name}\n"
    )


def test_generate_manifest_rejects_filename_mismatch(tmp_path):
    installer = tmp_path / "wrong.exe"
    installer.write_bytes(b"x")
    with pytest.raises(ValueError):
        generate_manifest(installer, "1.2.3", "a" * 40)
