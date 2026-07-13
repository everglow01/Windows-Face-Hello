"""为最终安装包生成 updater manifest 与 SHA-256 文件。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from face_hello.version import parse_stable_version  # noqa: E402

_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")


def generate_manifest(installer: Path, version_text: str, commit: str) -> dict:
    version = parse_stable_version(version_text)
    expected_name = f"FaceHello-Setup-{version}.exe"
    if installer.name != expected_name:
        raise ValueError(f"installer must be named {expected_name}")
    if _COMMIT_RE.fullmatch(commit) is None:
        raise ValueError("commit must be a full lowercase SHA")
    size = installer.stat().st_size
    if size <= 0:
        raise ValueError("installer is empty")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    return {
        "channel": "stable",
        "installer": {"name": installer.name, "sha256": digest, "size": size},
        "minimum_supported_version": "1.0.0",
        "product": "FaceHello",
        "release_commit": commit,
        "schema_version": 1,
        "tag": f"v{version}",
        "version": str(version),
    }


def write_release_metadata(installer: Path, version: str, commit: str, output: Path) -> None:
    manifest = generate_manifest(installer, version, commit)
    output.mkdir(parents=True, exist_ok=True)
    (output / "facehello-update.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    digest = manifest["installer"]["sha256"]
    (output / f"{installer.name}.sha256").write_text(
        f"{digest}  {installer.name}\n", encoding="ascii"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("installer", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_release_metadata(args.installer, args.version, args.commit, args.output)


if __name__ == "__main__":
    main()
