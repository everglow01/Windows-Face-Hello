"""GitHub Releases 更新检查与可恢复下载；不依赖 Qt。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .authenticode import AuthenticodeResult, verify_authenticode
from .version import Version, parse_stable_version

_REPOSITORY = "everglow01/Windows-Face-Hello"
_LATEST_RELEASE_URL = f"https://api.github.com/repos/{_REPOSITORY}/releases/latest"
_MANIFEST_NAME = "facehello-update.json"
_MAX_METADATA_BYTES = 256 * 1024
_MAX_INSTALLER_BYTES = 2 * 1024 * 1024 * 1024
_CHUNK_SIZE = 1024 * 1024
_ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
}
_CONTENT_RANGE_RE = re.compile(r"bytes (\d+)-(\d+)/(\d+)\Z")


class UpdateErrorCode(str, Enum):
    NETWORK = "network"
    RATE_LIMIT = "rate_limit"
    INVALID_RELEASE = "invalid_release"
    UNSUPPORTED_MANIFEST = "unsupported_manifest"
    DISK_SPACE = "disk_space"
    CANCELLED = "cancelled"
    DOWNLOAD = "download"
    VERIFY = "verify"


class UpdateError(RuntimeError):
    def __init__(self, code: UpdateErrorCode, detail: str = "") -> None:
        super().__init__(detail or code.value)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ReleaseAsset:
    asset_id: int
    name: str
    size: int
    url: str


@dataclass(frozen=True)
class UpdateManifest:
    version: Version
    tag: str
    installer_name: str
    installer_size: int
    installer_sha256: str
    release_commit: str
    minimum_supported_version: Version


@dataclass(frozen=True)
class UpdateCandidate:
    release_id: int
    version: Version
    tag: str
    release_url: str
    release_notes: str
    installer: ReleaseAsset
    manifest: UpdateManifest
    is_newer: bool | None


@dataclass(frozen=True)
class DownloadProgress:
    downloaded: int
    total: int


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    resumed: bool


def _require_dict(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, f"{label} must be an object")
    return value


def _require_str(value, label: str, max_length: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, f"invalid {label}")
    return value


def _require_int(value, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, f"invalid {label}")
    return value


def _parse_json(raw: bytes, label: str) -> dict:
    if len(raw) > _MAX_METADATA_BYTES:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, f"{label} is too large")
    try:
        return _require_dict(json.loads(raw.decode("utf-8")), label)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, f"invalid {label}") from exc


def _parse_version(value: object, label: str) -> Version:
    try:
        return parse_stable_version(_require_str(value, label, 64))
    except ValueError as exc:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, f"invalid {label}") from exc


def parse_manifest(raw: bytes) -> UpdateManifest:
    data = _parse_json(raw, "manifest")
    if data.get("schema_version") != 1:
        raise UpdateError(UpdateErrorCode.UNSUPPORTED_MANIFEST, "unsupported manifest schema")
    if data.get("product") != "FaceHello" or data.get("channel") != "stable":
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "wrong product or channel")
    version = _parse_version(data.get("version"), "manifest version")
    tag = _require_str(data.get("tag"), "manifest tag", 65)
    if tag != f"v{version}":
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "manifest tag mismatch")
    installer = _require_dict(data.get("installer"), "installer")
    name = _require_str(installer.get("name"), "installer name", 128)
    if name != f"FaceHello-Setup-{version}.exe":
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "installer name mismatch")
    size = _require_int(installer.get("size"), "installer size", 1)
    if size > _MAX_INSTALLER_BYTES:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "installer is too large")
    sha256 = _require_str(installer.get("sha256"), "installer sha256", 64)
    if re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "invalid installer sha256")
    commit = _require_str(data.get("release_commit"), "release commit", 64)
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "invalid release commit")
    minimum = _parse_version(data.get("minimum_supported_version"), "minimum version")
    return UpdateManifest(version, tag, name, size, sha256, commit, minimum)


def _parse_assets(value: object) -> list[ReleaseAsset]:
    if not isinstance(value, list) or len(value) > 32:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "invalid release assets")
    result = []
    for item in value:
        asset = _require_dict(item, "asset")
        result.append(
            ReleaseAsset(
                _require_int(asset.get("id"), "asset id", 1),
                _require_str(asset.get("name"), "asset name", 128),
                _require_int(asset.get("size"), "asset size", 1),
                _require_str(asset.get("browser_download_url"), "asset url", 2048),
            )
        )
    return result


def parse_release(raw: bytes) -> tuple[dict, list[ReleaseAsset]]:
    data = _parse_json(raw, "release")
    if data.get("draft") is not False or data.get("prerelease") is not False:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "release is not stable")
    tag = _require_str(data.get("tag_name"), "release tag", 65)
    try:
        version = parse_stable_version(tag.removeprefix("v"))
    except ValueError as exc:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "invalid release tag") from exc
    if tag != f"v{version}":
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "invalid release tag")
    data["_version"] = version
    return data, _parse_assets(data.get("assets"))


def select_candidate(
    release_raw: bytes,
    manifest_raw: bytes,
    current_version: Version | None,
) -> UpdateCandidate:
    release, assets = parse_release(release_raw)
    manifest = parse_manifest(manifest_raw)
    version = release["_version"]
    if manifest.version != version or manifest.tag != release["tag_name"]:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "release and manifest mismatch")
    matching = [asset for asset in assets if asset.name == manifest.installer_name]
    manifests = [asset for asset in assets if asset.name == _MANIFEST_NAME]
    if len(matching) != 1 or len(manifests) != 1:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "missing or duplicate release assets")
    installer = matching[0]
    if installer.size != manifest.installer_size:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "installer size mismatch")
    release_id = _require_int(release.get("id"), "release id", 1)
    release_url = _require_str(release.get("html_url"), "release url", 2048)
    notes = release.get("body") or ""
    if not isinstance(notes, str):
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "invalid release notes")
    notes = notes[:20000]
    is_newer = None if current_version is None else version > current_version
    return UpdateCandidate(
        release_id, version, manifest.tag, release_url, notes, installer, manifest, is_newer
    )


def _validate_https_url(url: str, allowed_hosts: set[str], label: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, f"untrusted {label} URL")


def _request_bytes(
    url: str,
    timeout: float,
    opener=urllib.request.urlopen,
    *,
    allowed_final_hosts: set[str] | None = None,
) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "FaceHello-Updater",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            if allowed_final_hosts is not None:
                _validate_https_url(response.geturl(), allowed_final_hosts, "metadata")
            raw = response.read(_MAX_METADATA_BYTES + 1)
    except urllib.error.HTTPError as exc:
        code = UpdateErrorCode.RATE_LIMIT if exc.code == 429 else UpdateErrorCode.NETWORK
        raise UpdateError(code, f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(UpdateErrorCode.NETWORK, str(exc)) from exc
    if len(raw) > _MAX_METADATA_BYTES:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "metadata is too large")
    return raw


def check_latest(
    current_version: Version | None,
    *,
    opener=urllib.request.urlopen,
) -> UpdateCandidate:
    release_raw = _request_bytes(
        _LATEST_RELEASE_URL, 20, opener, allowed_final_hosts={"api.github.com"}
    )
    release, assets = parse_release(release_raw)
    manifest_assets = [asset for asset in assets if asset.name == _MANIFEST_NAME]
    if len(manifest_assets) != 1:
        raise UpdateError(UpdateErrorCode.INVALID_RELEASE, "missing or duplicate manifest")
    _validate_https_url(
        manifest_assets[0].url, {"github.com", "objects.githubusercontent.com"}, "manifest"
    )
    manifest_raw = _request_bytes(
        manifest_assets[0].url,
        20,
        opener,
        allowed_final_hosts=_ALLOWED_DOWNLOAD_HOSTS,
    )
    return select_candidate(release_raw, manifest_raw, current_version)


def default_cache_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        local = str(Path.home() / "AppData" / "Local")
    return Path(local) / "FaceHello" / "updates"


def _cache_paths(candidate: UpdateCandidate, cache_root: Path) -> tuple[Path, Path, Path]:
    directory = cache_root / str(candidate.version)
    final = directory / candidate.installer.name
    return final.with_suffix(final.suffix + ".part"), directory / "download-state.json", final


def _atomic_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _state_for(candidate: UpdateCandidate, etag: str = "", last_modified: str = "") -> dict:
    return {
        "schema_version": 1,
        "repository": _REPOSITORY,
        "release_id": candidate.release_id,
        "asset_id": candidate.installer.asset_id,
        "asset_name": candidate.installer.name,
        "asset_url": candidate.installer.url,
        "version": str(candidate.version),
        "expected_size": candidate.manifest.installer_size,
        "expected_sha256": candidate.manifest.installer_sha256,
        "etag": etag,
        "last_modified": last_modified,
    }


def _load_resume_state(path: Path, candidate: UpdateCandidate) -> dict | None:
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    expected = _state_for(candidate)
    for key in (
        "schema_version",
        "repository",
        "release_id",
        "asset_id",
        "asset_name",
        "asset_url",
        "version",
        "expected_size",
        "expected_sha256",
    ):
        if state.get(key) != expected[key]:
            return None
    return state


def verify_installer(
    path: Path,
    candidate: UpdateCandidate,
    signer_sha256: tuple[str, ...] = (),
    *,
    signature_verifier: Callable[[Path, tuple[str, ...]], AuthenticodeResult] = verify_authenticode,
) -> None:
    """重新核对已下载安装包的大小、SHA-256 和发布者签名。"""
    if not path.is_file() or path.stat().st_size != candidate.manifest.installer_size:
        raise UpdateError(UpdateErrorCode.VERIFY, "installer size mismatch")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    if digest.hexdigest() != candidate.manifest.installer_sha256:
        raise UpdateError(UpdateErrorCode.VERIFY, "installer sha256 mismatch")
    if signer_sha256 and not signature_verifier(path, signer_sha256).trusted:
        raise UpdateError(UpdateErrorCode.VERIFY, "installer signature mismatch")


def _verified(path: Path, candidate: UpdateCandidate) -> bool:
    try:
        verify_installer(path, candidate)
    except (OSError, UpdateError):
        return False
    return True


def _validate_download_url(url: str, allow_http: bool) -> None:
    parsed = urlparse(url)
    if allow_http and parsed.scheme == "http":
        return
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_DOWNLOAD_HOSTS:
        raise UpdateError(UpdateErrorCode.DOWNLOAD, "untrusted download URL")


def _open_download(request, timeout, opener):
    try:
        return opener(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 416:
            return exc
        code = UpdateErrorCode.RATE_LIMIT if exc.code == 429 else UpdateErrorCode.NETWORK
        raise UpdateError(code, f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(UpdateErrorCode.NETWORK, str(exc)) from exc


def _download_once(
    candidate: UpdateCandidate,
    *,
    cache_root: Path | None = None,
    progress: Callable[[DownloadProgress], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    opener=urllib.request.urlopen,
    allow_http_for_tests: bool = False,
) -> DownloadResult:
    """下载或续传安装包；完整大小和哈希通过后才返回 .exe。"""
    cache_root = cache_root or default_cache_root()
    part, state_path, final = _cache_paths(candidate, cache_root)
    final.parent.mkdir(parents=True, exist_ok=True)
    if _verified(final, candidate):
        return DownloadResult(final, resumed=False)
    final.unlink(missing_ok=True)

    state = _load_resume_state(state_path, candidate)
    if state is None:
        part.unlink(missing_ok=True)
        state_path.unlink(missing_ok=True)
        state = _state_for(candidate)
    current = part.stat().st_size if part.exists() else 0
    expected = candidate.manifest.installer_size
    if current > expected:
        part.unlink()
        current = 0
    free = shutil.disk_usage(final.parent).free
    if free < expected - current + 64 * 1024 * 1024:
        raise UpdateError(UpdateErrorCode.DISK_SPACE, "not enough free space")

    _validate_download_url(candidate.installer.url, allow_http_for_tests)
    headers = {"Accept-Encoding": "identity", "User-Agent": "FaceHello-Updater"}
    resumed = current > 0
    if current:
        headers["Range"] = f"bytes={current}-"
        etag = state.get("etag", "")
        modified = state.get("last_modified", "")
        if isinstance(etag, str) and etag and not etag.startswith("W/"):
            headers["If-Range"] = etag
        elif isinstance(modified, str) and modified:
            headers["If-Range"] = modified
    response = _open_download(
        urllib.request.Request(candidate.installer.url, headers=headers), 60, opener
    )
    try:
        status = getattr(response, "status", response.getcode())
        final_url = response.geturl()
        _validate_download_url(final_url, allow_http_for_tests)
        if response.headers.get("Content-Encoding", "identity").lower() not in ("", "identity"):
            raise UpdateError(UpdateErrorCode.DOWNLOAD, "unexpected content encoding")
        if current and status == 206:
            match = _CONTENT_RANGE_RE.fullmatch(response.headers.get("Content-Range", ""))
            if match is None or int(match.group(1)) != current or int(match.group(3)) != expected:
                raise UpdateError(UpdateErrorCode.DOWNLOAD, "invalid content range")
            mode = "ab"
        elif status == 200:
            current = 0
            resumed = False
            mode = "wb"
        elif status == 416:
            if current == expected and _verified(part, candidate):
                os.replace(part, final)
                state_path.unlink(missing_ok=True)
                return DownloadResult(final, resumed=True)
            part.unlink(missing_ok=True)
            state_path.unlink(missing_ok=True)
            raise UpdateError(UpdateErrorCode.DOWNLOAD, "invalid partial download")
        else:
            raise UpdateError(UpdateErrorCode.DOWNLOAD, f"unexpected HTTP status {status}")

        state = _state_for(
            candidate,
            response.headers.get("ETag", ""),
            response.headers.get("Last-Modified", ""),
        )
        _atomic_json(state_path, state)
        downloaded = current
        with part.open(mode) as stream:
            while True:
                if should_cancel and should_cancel():
                    raise UpdateError(UpdateErrorCode.CANCELLED)
                try:
                    chunk = response.read(_CHUNK_SIZE)
                except (TimeoutError, OSError) as exc:
                    raise UpdateError(UpdateErrorCode.NETWORK, str(exc)) from exc
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > expected:
                    raise UpdateError(UpdateErrorCode.DOWNLOAD, "download exceeds expected size")
                stream.write(chunk)
                if progress:
                    progress(DownloadProgress(downloaded, expected))
            stream.flush()
            os.fsync(stream.fileno())
    except UpdateError as exc:
        if exc.code in (UpdateErrorCode.DOWNLOAD, UpdateErrorCode.VERIFY):
            part.unlink(missing_ok=True)
            state_path.unlink(missing_ok=True)
        raise
    finally:
        response.close()

    if part.stat().st_size != expected or not _verified(part, candidate):
        part.unlink(missing_ok=True)
        state_path.unlink(missing_ok=True)
        raise UpdateError(UpdateErrorCode.VERIFY, "installer size or sha256 mismatch")
    os.replace(part, final)
    state_path.unlink(missing_ok=True)
    return DownloadResult(final, resumed=resumed)


def download_installer(
    candidate: UpdateCandidate,
    *,
    cache_root: Path | None = None,
    progress: Callable[[DownloadProgress], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    opener=urllib.request.urlopen,
    allow_http_for_tests: bool = False,
    max_attempts: int = 4,
) -> DownloadResult:
    """下载安装包，瞬时网络错误有限重试，每次都从现有断点继续。"""
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    for attempt in range(max_attempts):
        try:
            return _download_once(
                candidate,
                cache_root=cache_root,
                progress=progress,
                should_cancel=should_cancel,
                opener=opener,
                allow_http_for_tests=allow_http_for_tests,
            )
        except UpdateError as exc:
            if exc.code not in (UpdateErrorCode.NETWORK, UpdateErrorCode.RATE_LIMIT):
                raise
            if attempt + 1 >= max_attempts:
                raise
            delay = min(2**attempt, 8)
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                if should_cancel and should_cancel():
                    raise UpdateError(UpdateErrorCode.CANCELLED) from exc
                time.sleep(min(0.1, deadline - time.monotonic()))
    raise AssertionError("unreachable")


def purge_cache(cache_root: Path | None = None, max_age_days: int = 30) -> None:
    root = (cache_root or default_cache_root()).resolve()
    if not root.exists():
        return
    cutoff = time.time() - max_age_days * 86400
    for child in root.iterdir():
        if not child.is_dir():
            continue
        files = list(child.iterdir())
        if files and max(path.stat().st_mtime for path in files) < cutoff:
            shutil.rmtree(child)
