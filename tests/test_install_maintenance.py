from __future__ import annotations

import hashlib

import pywintypes
import pytest
import win32service

from scripts import install_maintenance


def test_import_signer_requires_pinned_certificate(tmp_path, monkeypatch):
    root = tmp_path / "FaceHello"
    root.mkdir()
    certificate = root / "FaceHello-Signer.cer"
    certificate.write_bytes(b"public certificate")
    digest = hashlib.sha256(certificate.read_bytes()).hexdigest()
    monkeypatch.setattr(install_maintenance.config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(install_maintenance, "_store_contains", lambda store, value: False)
    calls = []
    monkeypatch.setattr(install_maintenance, "_run", lambda *args: calls.append(args))

    markers = install_maintenance._import_signer(root, (digest,))

    assert [call[3] for call in calls] == ["Root", "TrustedPublisher"]
    assert len(markers) == 2
    assert len(list((tmp_path / "data").glob("signer-*.installed"))) == 2


def test_import_signer_rolls_back_partial_import(tmp_path, monkeypatch):
    root = tmp_path / "FaceHello"
    root.mkdir()
    certificate = root / "FaceHello-Signer.cer"
    certificate.write_bytes(b"public certificate")
    digest = hashlib.sha256(certificate.read_bytes()).hexdigest()
    data = tmp_path / "data"
    monkeypatch.setattr(install_maintenance.config, "DATA_DIR", data)
    monkeypatch.setattr(install_maintenance, "_store_contains", lambda store, value: False)
    call_count = 0

    def run(*args):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("second store failed")

    rolled_back = []
    monkeypatch.setattr(install_maintenance, "_run", run)
    monkeypatch.setattr(
        install_maintenance,
        "_rollback_signer",
        lambda markers: rolled_back.extend(markers),
    )

    with pytest.raises(RuntimeError, match="second store failed"):
        install_maintenance._import_signer(root, (digest,))

    assert rolled_back == [data / f"signer-root-{digest}.installed"]


def test_import_signer_rejects_unpinned_certificate(tmp_path):
    root = tmp_path / "FaceHello"
    root.mkdir()
    (root / "FaceHello-Signer.cer").write_bytes(b"wrong certificate")

    with pytest.raises(RuntimeError):
        install_maintenance._import_signer(root, ("0" * 64,))


def test_run_uses_bounded_timeout(monkeypatch):
    calls = []
    monkeypatch.setattr(
        install_maintenance.subprocess,
        "run",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )

    install_maintenance._run("tool.exe", "arg")

    assert calls == [
        (("tool.exe", "arg"), {"check": True, "timeout": 60})
    ]


def test_owned_cp_accepts_only_versioned_dll_below_root(tmp_path):
    root = tmp_path / "FaceHello"
    root.mkdir()
    assert install_maintenance._owned_cp(root / "FaceHelloCP-1.2.3.dll", root)
    assert install_maintenance._owned_cp(root / "FaceHelloCP.dll", root)
    assert not install_maintenance._owned_cp(
        tmp_path / "other" / "FaceHelloCP-1.2.3.dll", root
    )


def test_runtime_acl_targets_are_parent_first_and_skip_backup(tmp_path):
    root = tmp_path / "FaceHello"
    data = root / "data"
    data.mkdir(parents=True)
    (data / "service.log").write_text("old log", encoding="utf-8")
    backup = root / "update-backup"
    backup.mkdir()
    (backup / "python.exe").write_bytes(b"backup")

    targets = list(install_maintenance._runtime_acl_targets(root))

    assert targets[0] == root
    assert data in targets
    assert data / "service.log" in targets
    assert backup not in targets
    assert backup / "python.exe" not in targets
    assert targets.index(data) < targets.index(data / "service.log")


def test_runtime_acl_targets_reject_reparse_point(tmp_path, monkeypatch):
    root = tmp_path / "FaceHello"
    child = root / "link"
    child.mkdir(parents=True)
    monkeypatch.setattr(
        install_maintenance,
        "_is_reparse_point",
        lambda path: path == child,
    )

    with pytest.raises(RuntimeError, match="reparse point"):
        list(install_maintenance._runtime_acl_targets(root))


def test_runtime_dacl_allows_only_system_and_administrators():
    dacl, admins_sid = install_maintenance._runtime_dacl(True)
    system_sid = install_maintenance.win32security.CreateWellKnownSid(
        install_maintenance.win32security.WinLocalSystemSid
    )

    assert dacl.GetAceCount() == 2
    first = dacl.GetAce(0)
    second = dacl.GetAce(1)
    assert first[2] == system_sid
    assert second[2] == admins_sid
    expected_flags = (
        install_maintenance.win32security.OBJECT_INHERIT_ACE
        | install_maintenance.win32security.CONTAINER_INHERIT_ACE
    )
    assert first[0][1] == expected_flags
    assert second[0][1] == expected_flags
    assert first[1] == install_maintenance.ntsecuritycon.FILE_ALL_ACCESS
    assert second[1] == install_maintenance.ntsecuritycon.FILE_ALL_ACCESS


def test_repair_runtime_acl_recovers_access_denied_and_checks_log(tmp_path, monkeypatch):
    root = tmp_path / "FaceHello"
    data = root / "data"
    data.mkdir(parents=True)
    log = data / "service.log"
    log.write_text("existing", encoding="utf-8")
    monkeypatch.setattr(install_maintenance.config, "AVATAR_DIR", root)
    monkeypatch.setattr(install_maintenance.config, "DATA_DIR", data)
    set_calls = []
    recovered = []

    def set_acl(path, is_directory):
        set_calls.append((path, is_directory))
        if path == log and path not in recovered:
            raise pywintypes.error(5, "SetNamedSecurityInfo", "Access is denied")

    monkeypatch.setattr(install_maintenance, "_set_runtime_dacl", set_acl)
    monkeypatch.setattr(
        install_maintenance,
        "_take_ownership",
        lambda path, is_directory: recovered.append(path),
    )

    install_maintenance._repair_runtime_acl()

    assert set_calls[0] == (root, True)
    assert log in recovered
    assert log.read_text(encoding="utf-8") == "existing"


def test_repair_runtime_acl_reports_log_preflight_failure(tmp_path, monkeypatch):
    root = tmp_path / "FaceHello"
    data = root / "data"
    data.mkdir(parents=True)
    log = data / "service.log"
    log.mkdir()
    monkeypatch.setattr(install_maintenance.config, "AVATAR_DIR", root)
    monkeypatch.setattr(install_maintenance.config, "DATA_DIR", data)
    monkeypatch.setattr(install_maintenance, "_set_runtime_dacl", lambda path, is_dir: None)

    with pytest.raises(RuntimeError, match="cannot append service log"):
        install_maintenance._repair_runtime_acl()


def test_stop_service_accepts_already_stopped_service(tmp_path, monkeypatch):
    monkeypatch.setattr(
        install_maintenance,
        "_service_status",
        lambda: {"CurrentState": win32service.SERVICE_STOPPED},
    )
    monkeypatch.setattr(
        install_maintenance,
        "_run",
        lambda *args: (_ for _ in ()).throw(AssertionError("stop should not run")),
    )

    install_maintenance._stop_service(tmp_path)


def test_wait_ready_accepts_expected_pipe_response(monkeypatch):
    monkeypatch.setattr(
        install_maintenance.probes,
        "call_pipe",
        lambda request: {
            "ok": True,
            "ready": True,
            "version": "1.1.0",
            "protocol": 1,
        },
    )
    monkeypatch.setattr(
        install_maintenance,
        "_service_status",
        lambda: (_ for _ in ()).throw(AssertionError("SCM should not be queried")),
    )

    install_maintenance._wait_ready("1.1.0", timeout=0.1)


def test_wait_ready_reports_wrong_service_version_immediately(monkeypatch):
    monkeypatch.setattr(
        install_maintenance.probes,
        "call_pipe",
        lambda request: {
            "ok": True,
            "ready": True,
            "version": "1.0.0",
            "protocol": 1,
        },
    )
    monkeypatch.setattr(
        install_maintenance,
        "_service_status",
        lambda: (_ for _ in ()).throw(AssertionError("SCM should not be queried")),
    )

    with pytest.raises(RuntimeError, match=r"expected=1\.1\.0, actual=1\.0\.0"):
        install_maintenance._wait_ready("1.1.0", timeout=120)


def test_wait_ready_fails_immediately_when_service_stops(monkeypatch):
    monkeypatch.setattr(
        install_maintenance.probes,
        "call_pipe",
        lambda request: (_ for _ in ()).throw(OSError("pipe unavailable")),
    )
    monkeypatch.setattr(
        install_maintenance,
        "_service_status",
        lambda: {
            "CurrentState": win32service.SERVICE_STOPPED,
            "Win32ExitCode": 1066,
            "ServiceSpecificExitCode": 0x20000001,
        },
    )

    with pytest.raises(RuntimeError, match="win32=1066, service=536870913"):
        install_maintenance._wait_ready("1.1.0", timeout=120)


def _configure_fixture(tmp_path, monkeypatch, *, old_cp=False):
    root = tmp_path / "FaceHello"
    root.mkdir()
    new_cp = root / "FaceHelloCP-1.1.0.dll"
    new_cp.write_bytes(b"new")
    (root / "winservice_main.py").write_text("", encoding="utf-8")
    previous = None
    if old_cp:
        previous = root / "FaceHelloCP-1.0.0.dll"
        previous.write_bytes(b"old")
    monkeypatch.setattr(install_maintenance.config, "INSTALL_ROOT", root)
    monkeypatch.setattr(install_maintenance, "display_version", lambda: "1.1.0")
    monkeypatch.setattr(install_maintenance, "_registered_cp", lambda: previous)
    monkeypatch.setattr(install_maintenance, "_repair_runtime_acl", lambda: None)
    monkeypatch.setattr(install_maintenance, "_import_signer", lambda root, signers: [])
    return root, previous, new_cp


def test_configure_acl_failure_does_not_touch_service_or_cp(tmp_path, monkeypatch):
    root, _old_cp, _new_cp = _configure_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        install_maintenance,
        "_repair_runtime_acl",
        lambda: (_ for _ in ()).throw(RuntimeError("acl failed")),
    )
    run_calls = []
    cp_calls = []
    monkeypatch.setattr(install_maintenance, "_run", lambda *args: run_calls.append(args))
    monkeypatch.setattr(install_maintenance, "_register", lambda path: cp_calls.append(path))

    with pytest.raises(RuntimeError, match="acl failed"):
        install_maintenance.configure("update", True)

    assert (root / ".installed").is_file()
    assert run_calls == []
    assert cp_calls == []


def test_configure_runs_acceptance_after_ready(tmp_path, monkeypatch):
    root, _old_cp, _new_cp = _configure_fixture(tmp_path, monkeypatch)
    baseline = tmp_path / "doctor-baseline.json"
    events = []
    monkeypatch.setattr(
        install_maintenance,
        "_capture_acceptance_baseline",
        lambda actual_root, actual_baseline: events.append(
            ("capture", actual_root, actual_baseline)
        ),
    )
    monkeypatch.setattr(
        install_maintenance,
        "_run_installed_acceptance",
        lambda actual_root, actual_baseline: events.append(
            ("accept", actual_root, actual_baseline)
        ),
    )
    monkeypatch.setattr(
        install_maintenance,
        "_wait_ready",
        lambda version: events.append(("ready", version)),
    )
    monkeypatch.setattr(install_maintenance, "_register", lambda path: None)
    monkeypatch.setattr(install_maintenance, "_run", lambda *args: None)

    baseline.write_text("baseline", encoding="utf-8")
    install_maintenance.configure("update", True, baseline)

    assert events == [
        ("capture", root, baseline),
        ("ready", "1.1.0"),
        ("accept", root, baseline),
    ]
    assert not baseline.exists()


def test_configure_temporarily_starts_service_for_acceptance(tmp_path, monkeypatch):
    root, _old_cp, _new_cp = _configure_fixture(tmp_path, monkeypatch)
    baseline = tmp_path / "doctor-baseline.json"
    run_calls = []
    stopped = []
    monkeypatch.setattr(
        install_maintenance, "_capture_acceptance_baseline", lambda root, path: None
    )
    monkeypatch.setattr(
        install_maintenance, "_run_installed_acceptance", lambda root, path: None
    )
    monkeypatch.setattr(install_maintenance, "_wait_ready", lambda version: None)
    monkeypatch.setattr(install_maintenance, "_register", lambda path: None)
    monkeypatch.setattr(
        install_maintenance, "_run", lambda *args: run_calls.append(args)
    )
    monkeypatch.setattr(
        install_maintenance, "_stop_service", lambda actual_root: stopped.append(actual_root)
    )

    install_maintenance.configure("update", False, baseline)

    service_actions = [call[-1] for call in run_calls if "winservice_main.py" in call[1]]
    assert service_actions == ["update", "start"]
    assert stopped == [root]


def test_acceptance_failure_uses_existing_cleanup(tmp_path, monkeypatch):
    root, old_cp, new_cp = _configure_fixture(tmp_path, monkeypatch, old_cp=True)
    baseline = tmp_path / "doctor-baseline.json"
    cp_calls = []
    stopped = []
    monkeypatch.setattr(
        install_maintenance, "_capture_acceptance_baseline", lambda root, path: None
    )
    monkeypatch.setattr(install_maintenance, "_wait_ready", lambda version: None)
    monkeypatch.setattr(
        install_maintenance,
        "_run_installed_acceptance",
        lambda root, path: (_ for _ in ()).throw(RuntimeError("acceptance failed")),
    )
    monkeypatch.setattr(
        install_maintenance, "_register", lambda path: cp_calls.append(("reg", path))
    )
    monkeypatch.setattr(
        install_maintenance, "_unregister", lambda path: cp_calls.append(("unreg", path))
    )
    monkeypatch.setattr(install_maintenance, "_run", lambda *args: None)
    monkeypatch.setattr(
        install_maintenance, "_stop_service", lambda actual_root: stopped.append(actual_root)
    )

    baseline.write_text("baseline", encoding="utf-8")
    with pytest.raises(RuntimeError, match="acceptance failed"):
        install_maintenance.configure("update", True, baseline)

    assert baseline.exists()
    assert stopped == [root]
    assert cp_calls == [("reg", new_cp), ("unreg", new_cp), ("reg", old_cp)]


def test_configure_failure_restores_cp_without_restarting_old_service(
    tmp_path, monkeypatch
):
    _root, old_cp, new_cp = _configure_fixture(tmp_path, monkeypatch, old_cp=True)
    cp_calls = []
    run_calls = []
    monkeypatch.setattr(
        install_maintenance, "_register", lambda path: cp_calls.append(("reg", path))
    )
    monkeypatch.setattr(
        install_maintenance, "_unregister", lambda path: cp_calls.append(("unreg", path))
    )
    monkeypatch.setattr(install_maintenance, "_run", lambda *args: run_calls.append(args))
    monkeypatch.setattr(
        install_maintenance,
        "_stop_service",
        lambda root: run_calls.append(("cleanup", "stop")),
    )
    monkeypatch.setattr(
        install_maintenance,
        "_wait_ready",
        lambda version: (_ for _ in ()).throw(RuntimeError("not ready")),
    )

    with pytest.raises(RuntimeError, match="not ready"):
        install_maintenance.configure("update", True)

    assert cp_calls == [("reg", new_cp), ("unreg", new_cp), ("reg", old_cp)]
    service_actions = [call[-1] for call in run_calls if "winservice_main.py" in call[1]]
    assert service_actions == ["update", "start"]
    assert ("cleanup", "stop") in run_calls


def test_first_install_failure_removes_new_service(tmp_path, monkeypatch):
    _root, _old_cp, new_cp = _configure_fixture(tmp_path, monkeypatch)
    cp_calls = []
    run_calls = []
    monkeypatch.setattr(
        install_maintenance, "_register", lambda path: cp_calls.append(("reg", path))
    )
    monkeypatch.setattr(
        install_maintenance, "_unregister", lambda path: cp_calls.append(("unreg", path))
    )
    monkeypatch.setattr(install_maintenance, "_run", lambda *args: run_calls.append(args))
    monkeypatch.setattr(
        install_maintenance,
        "_stop_service",
        lambda root: run_calls.append(("cleanup", "stop")),
    )
    monkeypatch.setattr(
        install_maintenance,
        "_wait_ready",
        lambda version: (_ for _ in ()).throw(RuntimeError("not ready")),
    )

    with pytest.raises(RuntimeError, match="not ready"):
        install_maintenance.configure("install", True)

    assert cp_calls == [("reg", new_cp), ("unreg", new_cp)]
    service_actions = [call[-1] for call in run_calls if "winservice_main.py" in call[1]]
    assert service_actions == ["install", "start", "remove"]
    assert ("cleanup", "stop") in run_calls
