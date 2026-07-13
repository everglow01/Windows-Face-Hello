from __future__ import annotations

import hashlib
import io
import json
from email.message import Message

import pytest

from face_hello.updater import (
    UpdateError,
    UpdateErrorCode,
    download_installer,
    parse_manifest,
    select_candidate,
)
from face_hello.version import Version


def _manifest(payload: bytes, version: str = "1.2.3") -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "product": "FaceHello",
            "channel": "stable",
            "version": version,
            "tag": f"v{version}",
            "installer": {
                "name": f"FaceHello-Setup-{version}.exe",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            },
            "release_commit": "a" * 40,
            "minimum_supported_version": "1.0.0",
        }
    ).encode()


def _release(payload: bytes, base_url: str, version: str = "1.2.3") -> bytes:
    return json.dumps(
        {
            "id": 12,
            "draft": False,
            "prerelease": False,
            "tag_name": f"v{version}",
            "html_url": "https://github.com/everglow01/Windows-Face-Hello/releases/tag/v1.2.3",
            "body": "notes",
            "assets": [
                {
                    "id": 21,
                    "name": f"FaceHello-Setup-{version}.exe",
                    "size": len(payload),
                    "browser_download_url": f"{base_url}/installer",
                },
                {
                    "id": 22,
                    "name": "facehello-update.json",
                    "size": 100,
                    "browser_download_url": f"{base_url}/manifest",
                },
            ],
        }
    ).encode()


def _candidate(payload: bytes, base_url: str = "http://localhost"):
    return select_candidate(_release(payload, base_url), _manifest(payload), Version(1, 0, 0))


class Response(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None):
        super().__init__(body)
        self.status = status
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value

    def getcode(self):
        return self.status

    def geturl(self):
        return "http://localhost/installer"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_select_candidate_validates_and_compares_version():
    payload = b"installer"
    candidate = _candidate(payload)
    assert candidate.version == Version(1, 2, 3)
    assert candidate.is_newer is True
    assert candidate.manifest.installer_sha256 == hashlib.sha256(payload).hexdigest()


def test_development_candidate_has_no_upgrade_comparison():
    payload = b"installer"
    candidate = select_candidate(_release(payload, "http://localhost"), _manifest(payload), None)
    assert candidate.is_newer is None


def test_manifest_rejects_unknown_schema():
    data = json.loads(_manifest(b"x"))
    data["schema_version"] = 2
    with pytest.raises(UpdateError) as exc:
        parse_manifest(json.dumps(data).encode())
    assert exc.value.code == UpdateErrorCode.UNSUPPORTED_MANIFEST


def test_release_rejects_asset_size_mismatch():
    payload = b"installer"
    release = json.loads(_release(payload, "http://localhost"))
    release["assets"][0]["size"] += 1
    with pytest.raises(UpdateError):
        select_candidate(json.dumps(release).encode(), _manifest(payload), Version(1, 0, 0))


def test_full_download_verifies_and_renames(tmp_path):
    payload = b"new installer bytes"
    candidate = _candidate(payload)

    result = download_installer(
        candidate,
        cache_root=tmp_path,
        opener=lambda request, timeout: Response(payload),
        allow_http_for_tests=True,
    )

    assert result.path.read_bytes() == payload
    assert result.path.suffix == ".exe"
    assert not list(tmp_path.rglob("*.part"))


def test_resume_appends_valid_206(tmp_path):
    payload = b"0123456789"
    candidate = _candidate(payload)
    version_dir = tmp_path / "1.2.3"
    version_dir.mkdir()
    part = version_dir / "FaceHello-Setup-1.2.3.exe.part"
    part.write_bytes(payload[:4])
    state = {
        "schema_version": 1,
        "repository": "everglow01/Windows-Face-Hello",
        "release_id": 12,
        "asset_id": 21,
        "asset_name": "FaceHello-Setup-1.2.3.exe",
        "asset_url": "http://localhost/installer",
        "version": "1.2.3",
        "expected_size": len(payload),
        "expected_sha256": hashlib.sha256(payload).hexdigest(),
        "etag": '"stable"',
        "last_modified": "",
    }
    (version_dir / "download-state.json").write_text(json.dumps(state), encoding="utf-8")
    seen = {}

    def opener(request, timeout):
        seen.update(dict(request.header_items()))
        return Response(
            payload[4:],
            status=206,
            headers={"Content-Range": f"bytes 4-9/{len(payload)}", "ETag": '"stable"'},
        )

    result = download_installer(
        candidate,
        cache_root=tmp_path,
        opener=opener,
        allow_http_for_tests=True,
    )

    assert result.resumed
    assert result.path.read_bytes() == payload
    assert seen["Range"] == "bytes=4-"
    assert seen["If-range"] == '"stable"'


def test_range_ignored_restarts_instead_of_appending(tmp_path):
    payload = b"0123456789"
    candidate = _candidate(payload)
    version_dir = tmp_path / "1.2.3"
    version_dir.mkdir()
    part = version_dir / "FaceHello-Setup-1.2.3.exe.part"
    part.write_bytes(payload[:4])
    state = {
        "schema_version": 1,
        "repository": "everglow01/Windows-Face-Hello",
        "release_id": 12,
        "asset_id": 21,
        "asset_name": "FaceHello-Setup-1.2.3.exe",
        "asset_url": "http://localhost/installer",
        "version": "1.2.3",
        "expected_size": len(payload),
        "expected_sha256": hashlib.sha256(payload).hexdigest(),
        "etag": '"stable"',
        "last_modified": "",
    }
    (version_dir / "download-state.json").write_text(json.dumps(state), encoding="utf-8")

    result = download_installer(
        candidate,
        cache_root=tmp_path,
        opener=lambda request, timeout: Response(payload, status=200),
        allow_http_for_tests=True,
    )

    assert not result.resumed
    assert result.path.read_bytes() == payload


def test_wrong_content_range_never_appends(tmp_path):
    payload = b"0123456789"
    candidate = _candidate(payload)
    version_dir = tmp_path / "1.2.3"
    version_dir.mkdir()
    part = version_dir / "FaceHello-Setup-1.2.3.exe.part"
    part.write_bytes(payload[:4])
    state = {
        "schema_version": 1,
        "repository": "everglow01/Windows-Face-Hello",
        "release_id": 12,
        "asset_id": 21,
        "asset_name": "FaceHello-Setup-1.2.3.exe",
        "asset_url": "http://localhost/installer",
        "version": "1.2.3",
        "expected_size": len(payload),
        "expected_sha256": hashlib.sha256(payload).hexdigest(),
        "etag": '"stable"',
        "last_modified": "",
    }
    (version_dir / "download-state.json").write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(UpdateError) as exc:
        download_installer(
            candidate,
            cache_root=tmp_path,
            opener=lambda request, timeout: Response(
                payload[4:], status=206, headers={"Content-Range": "bytes 3-9/10"}
            ),
            allow_http_for_tests=True,
        )
    assert exc.value.code == UpdateErrorCode.DOWNLOAD
    assert not part.exists()


def test_hash_mismatch_deletes_partial(tmp_path):
    payload = b"expected"
    candidate = _candidate(payload)
    with pytest.raises(UpdateError) as exc:
        download_installer(
            candidate,
            cache_root=tmp_path,
            opener=lambda request, timeout: Response(b"different"),
            allow_http_for_tests=True,
        )
    assert exc.value.code == UpdateErrorCode.DOWNLOAD
    assert not list(tmp_path.rglob("*.part"))
