from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import doctor


@pytest.fixture
def installed_config(monkeypatch, tmp_path):
    from face_hello import config

    root = tmp_path / "FaceHello"
    data = tmp_path / "ProgramData" / "data"
    root.mkdir()
    data.mkdir(parents=True)
    monkeypatch.setattr(config, "IS_INSTALLED", True)
    monkeypatch.setattr(config, "INSTALL_ROOT", root)
    monkeypatch.setattr(config, "CP_DLL", root / "FaceHelloCP-1.2.3.dll")
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "FACE_STORE", data / "faces.dat")
    return config


def test_check_build_rejects_development_mode(monkeypatch, capsys):
    from face_hello import config
    from face_hello import version

    monkeypatch.setattr(config, "IS_INSTALLED", False)
    monkeypatch.setattr(
        version,
        "get_build_info",
        lambda: SimpleNamespace(
            is_release=False, version="0.0.0-dev", tag="dev", commit="unknown"
        ),
    )

    assert doctor.check_build() is False
    assert "不是正式安装态" in capsys.readouterr().out


def test_check_service_deployment_requires_running_auto_and_exact_command(
    monkeypatch, installed_config
):
    from face_hello import probes

    python = installed_config.INSTALL_ROOT / "python" / "python.exe"
    launcher = installed_config.INSTALL_ROOT / "winservice_main.py"
    monkeypatch.setattr(
        probes,
        "query_service",
        lambda: probes.ServiceInfo(
            status=4,
            start_type=2,
            account="LocalSystem",
            image_path=f'"{python}" -u "{launcher}"',
        ),
    )

    assert doctor.check_service_deployment() is True

    monkeypatch.setattr(
        probes,
        "query_service",
        lambda: probes.ServiceInfo(
            status=1,
            start_type=3,
            account="LocalSystem",
            image_path=f'"{python}" -u "{launcher}"',
        ),
    )
    assert doctor.check_service_deployment() is False


def test_check_cp_deployment_rejects_stale_registered_dll(
    monkeypatch, installed_config
):
    installed_config.CP_DLL.write_bytes(b"current")
    monkeypatch.setattr(
        doctor,
        "_read_cp_registration",
        lambda: (True, installed_config.INSTALL_ROOT / "FaceHelloCP-1.2.2.dll"),
    )

    assert doctor.check_cp_deployment() is False

    monkeypatch.setattr(
        doctor,
        "_read_cp_registration",
        lambda: (True, installed_config.CP_DLL),
    )
    assert doctor.check_cp_deployment() is True


def test_check_service_log_does_not_change_content(installed_config):
    path = installed_config.DATA_DIR / "service.log"
    path.write_bytes(b"existing log\n")
    before = path.read_bytes()

    assert doctor.check_service_log() is True
    assert path.read_bytes() == before


def test_check_service_log_does_not_create_missing_file(installed_config):
    path = installed_config.DATA_DIR / "service.log"

    assert doctor.check_service_log() is False
    assert not path.exists()


def test_check_face_store_accepts_matching_ciphertext_baseline(
    monkeypatch, installed_config, capsys
):
    encrypted = b"encrypted face store"
    installed_config.FACE_STORE.write_bytes(encrypted)
    profiles = [SimpleNamespace(name="private-user", embedding=[1, 2, 3])]
    monkeypatch.setattr(
        "face_hello.store.FaceStore.load",
        lambda self: SimpleNamespace(list_profiles=lambda: profiles),
    )
    baseline = {"face_store_sha256": hashlib.sha256(encrypted).hexdigest()}

    assert doctor.check_face_store(baseline) is True
    output = capsys.readouterr().out
    assert "private-user" not in output
    assert "[1, 2, 3]" not in output

    baseline["face_store_sha256"] = "0" * 64
    assert doctor.check_face_store(baseline) is False


def test_check_face_store_rejects_missing_and_empty(installed_config):
    assert doctor.check_face_store() is False

    installed_config.FACE_STORE.write_bytes(b"")
    assert doctor.check_face_store() is False


def test_check_provider_safety_compares_baseline_without_inventory_leak(
    monkeypatch, capsys
):
    state = {
        "providers_sha256": "a" * 64,
        "provider_count": 4,
        "filters_sha256": "b" * 64,
        "filter_count": 1,
        "facehello_filter": False,
    }
    monkeypatch.setattr(doctor, "_provider_state", lambda: state)

    assert doctor.check_provider_safety(
        {"providers_sha256": "a" * 64, "filters_sha256": "b" * 64}
    )
    output = capsys.readouterr().out
    assert "a" * 64 not in output
    assert "b" * 64 not in output

    assert not doctor.check_provider_safety(
        {"providers_sha256": "c" * 64, "filters_sha256": "b" * 64}
    )


def test_check_provider_safety_rejects_facehello_filter(monkeypatch):
    monkeypatch.setattr(
        doctor,
        "_provider_state",
        lambda: {
            "providers_sha256": "a" * 64,
            "provider_count": 4,
            "filters_sha256": "b" * 64,
            "filter_count": 1,
            "facehello_filter": True,
        },
    )

    assert doctor.check_provider_safety() is False


def test_load_baseline_rejects_malformed_file(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

    with pytest.raises(ValueError, match="哈希无效"):
        doctor._load_baseline(path)


def test_capture_baseline_contains_only_safe_fields(
    monkeypatch, installed_config, tmp_path
):
    path = tmp_path / "baseline.json"
    monkeypatch.setattr(
        doctor,
        "_baseline_data",
        lambda: {
            "schema_version": 1,
            "face_store_sha256": "a" * 64,
            "face_store_size": 123,
            "face_store_profiles": 2,
            "providers_sha256": "b" * 64,
            "provider_count": 4,
            "filters_sha256": "c" * 64,
            "filter_count": 1,
        },
    )

    assert doctor.capture_baseline(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {
        "schema_version",
        "face_store_sha256",
        "face_store_size",
        "face_store_profiles",
        "providers_sha256",
        "provider_count",
        "filters_sha256",
        "filter_count",
    }
    serialized = path.read_text(encoding="utf-8")
    assert "password" not in serialized.casefold()
    assert "embedding" not in serialized.casefold()
    assert "username" not in serialized.casefold()


def test_run_installed_acceptance_requires_admin(monkeypatch):
    monkeypatch.setattr(doctor, "_is_admin", lambda: False)
    monkeypatch.setattr(
        doctor,
        "check_build",
        lambda: pytest.fail("checks must not run without admin"),
    )

    assert doctor.run_installed_acceptance(None) == 1


def test_copy_payload_includes_installed_doctor(monkeypatch, tmp_path):
    from scripts import build_release

    root = tmp_path / "root"
    build = tmp_path / "build"
    for directory in (root / "face_hello", root / "app", root / "scripts", root / "models"):
        directory.mkdir(parents=True, exist_ok=True)
    (root / "face_hello" / "module.py").write_text("", encoding="utf-8")
    (root / "app" / "module.py").write_text("", encoding="utf-8")
    for name in ("winservice_main.py", "uninstall_cleanup.py"):
        (root / name).write_text("", encoding="utf-8")
    for name in ("install_maintenance.py", "doctor.py"):
        (root / "scripts" / name).write_text(name, encoding="utf-8")
    (root / "models" / "model.onnx").write_bytes(b"model")
    dll = root / "cp" / "x64" / "Release" / "FaceHelloCP.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"dll")
    python_dir = tmp_path / "python"
    python_dir.mkdir()
    monkeypatch.setattr(build_release, "ROOT", root)
    monkeypatch.setattr(build_release, "BUILD", build)
    monkeypatch.setattr(build_release, "PYDIR", python_dir)
    monkeypatch.setattr(
        build_release,
        "_build_info",
        lambda version: {
            "version": version,
            "tag": f"v{version}",
            "commit": "abc",
            "signer_sha256": [],
        },
    )

    build_release.step_copy_payload("1.2.3")

    assert (build / "doctor.py").read_text(encoding="utf-8") == "doctor.py"
