from __future__ import annotations

import subprocess

import pytest

from scripts import build_release


@pytest.fixture
def payload(tmp_path, monkeypatch):
    root = tmp_path / "source"
    build = tmp_path / "build"
    python = build / "python"
    files = {
        "face_hello/config.py": b"config",
        "app/main.py": b"app",
        "winservice_main.py": b"service",
        "uninstall_cleanup.py": b"cleanup",
        "scripts/install_maintenance.py": b"maintenance",
        "scripts/doctor.py": b"doctor",
        "models/model.onnx": b"model",
        "cp/x64/Release/FaceHelloCP.dll": b"provider",
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    qt = python / "Lib/site-packages/PySide6"
    qt.mkdir(parents=True)
    for name in ("msvcp140.dll", "msvcp140_1.dll"):
        (qt / name).write_bytes(b"qt runtime")
    for name in ("vcruntime140.dll", "vcruntime140_1.dll"):
        (python / name).write_bytes(b"python runtime")
    monkeypatch.setattr(build_release, "ROOT", root)
    monkeypatch.setattr(build_release, "BUILD", build)
    monkeypatch.setattr(build_release, "PYDIR", python)
    monkeypatch.setattr(build_release, "_build_info", lambda version: {"version": version})
    return python, qt


def test_payload_includes_crt_without_replacing_python_runtime(payload):
    python, _qt = payload
    build_release.step_copy_payload("1.0.8")
    for name in ("msvcp140.dll", "msvcp140_1.dll"):
        assert (python / name).read_bytes() == b"qt runtime"
    for name in ("vcruntime140.dll", "vcruntime140_1.dll"):
        assert (python / name).read_bytes() == b"python runtime"


@pytest.mark.parametrize("name", ["msvcp140.dll", "msvcp140_1.dll",
                                 "vcruntime140.dll", "vcruntime140_1.dll"])
def test_payload_rejects_missing_runtime(payload, name):
    python, qt = payload
    ((qt if name.startswith("msvcp") else python) / name).unlink()
    with pytest.raises((FileNotFoundError, RuntimeError), match=name):
        build_release.step_copy_payload("1.0.8")


def test_smoke_stops_on_headless_import_failure(monkeypatch):
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        if "-I" in args:
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(build_release, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        build_release.step_smoke()
    assert len(calls) == 1
    assert calls[0][1:] == ("-I", "-c", "import onnxruntime")
