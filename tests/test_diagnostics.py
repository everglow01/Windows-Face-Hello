from __future__ import annotations

import types
import sys
import zipfile
from datetime import datetime

import pytest

from face_hello import diagnostics
from face_hello.diagnostics import DiagnosticItem, DiagnosticReport


def _report() -> DiagnosticReport:
    return DiagnosticReport(datetime(2026, 7, 3, 10, 0, 0), "development", "owen", False)


def test_diagnostic_report_text_is_stable() -> None:
    report = _report()
    report.items.append(DiagnosticItem("Service", diagnostics.STATUS_OK, "Running"))
    report.items.append(DiagnosticItem("Pipe", diagnostics.STATUS_WARN, "Access denied", "Run as admin"))

    text = report.to_text("en")

    assert "FaceHello Diagnostics" in text
    assert "Time: 2026-07-03T10:00:00" in text
    assert "Overall: OK" in text
    assert "- [OK] Service: Running" in text
    assert "- [Warning] Pipe: Access denied" in text
    assert "Advice: Run as admin" in text


def test_password_check_never_leaks_secret(monkeypatch) -> None:
    def retrieve_password(_user):
        return "top-secret-password"

    monkeypatch.setattr(diagnostics.cred_vault, "retrieve_password", retrieve_password)
    report = _report()

    diagnostics._check_password(report, "en", "owen")
    text = report.to_text("en")

    assert report.items[0].status == diagnostics.STATUS_OK
    assert "top-secret-password" not in text
    assert "yes" in text


def test_service_error_becomes_diagnostic_item(monkeypatch) -> None:
    def query_status(_name):
        raise RuntimeError("boom")

    fake_util = types.SimpleNamespace(QueryServiceStatus=query_status)
    monkeypatch.setitem(sys.modules, "win32con", types.SimpleNamespace(GENERIC_READ=1))
    monkeypatch.setitem(sys.modules, "win32service", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "win32serviceutil", fake_util)
    report = _report()

    diagnostics._check_service(report, "en")

    assert report.items[0].status == diagnostics.STATUS_FAIL
    assert "boom" in report.items[0].detail


def test_pipe_error_becomes_diagnostic_item(monkeypatch) -> None:
    def create_file(*args, **kwargs):
        raise RuntimeError("pipe boom")

    fake_file = types.SimpleNamespace(
        GENERIC_READ=1,
        GENERIC_WRITE=2,
        OPEN_EXISTING=3,
        CreateFile=create_file,
    )
    monkeypatch.setitem(sys.modules, "win32file", fake_file)
    monkeypatch.setitem(sys.modules, "win32pipe", types.SimpleNamespace())
    report = _report()

    diagnostics._check_pipe(report, "en")

    assert report.items[0].status == diagnostics.STATUS_FAIL
    assert "pipe boom" in report.items[0].detail


def test_pipe_health_reports_version_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        diagnostics.probes,
        "call_pipe",
        lambda request: {
            "ok": True,
            "ready": True,
            "version": "1.0.3",
            "protocol": 1,
        },
    )
    monkeypatch.setattr(diagnostics, "display_version", lambda: "1.0.4")
    report = _report()

    diagnostics._check_pipe(report, "en")

    assert report.items[0].status == diagnostics.STATUS_FAIL
    assert "app 1.0.4" in report.items[0].detail
    assert "service 1.0.3" in report.items[0].detail
    assert "repair or reinstall" in report.items[0].advice


def test_pipe_health_reports_protocol_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        diagnostics.probes,
        "call_pipe",
        lambda request: {
            "ok": True,
            "ready": True,
            "version": "1.0.4",
            "protocol": 2,
        },
    )
    monkeypatch.setattr(diagnostics, "display_version", lambda: "1.0.4")
    report = _report()

    diagnostics._check_pipe(report, "en")

    assert report.items[0].status == diagnostics.STATUS_FAIL
    assert "expected 1" in report.items[0].detail
    assert "service returned 2" in report.items[0].detail


def test_pipe_health_reports_not_ready(monkeypatch) -> None:
    monkeypatch.setattr(
        diagnostics.probes,
        "call_pipe",
        lambda request: {
            "ok": True,
            "ready": False,
            "version": "1.0.4",
            "protocol": 1,
        },
    )
    monkeypatch.setattr(diagnostics, "display_version", lambda: "1.0.4")
    report = _report()

    diagnostics._check_pipe(report, "en")

    assert report.items[0].status == diagnostics.STATUS_FAIL
    assert "warm-up" in report.items[0].detail
    assert "Wait for model warm-up" in report.items[0].advice


def test_run_diagnostics_includes_service_log_step(monkeypatch) -> None:
    steps = []
    monkeypatch.setattr(diagnostics.cred_vault, "current_user", lambda: "owen")
    monkeypatch.setattr(diagnostics, "_is_admin", lambda: True)
    monkeypatch.setattr(
        diagnostics,
        "_run_check",
        lambda _report, _lang, _progress, key, _func, *args: steps.append(key),
    )

    diagnostics.run_diagnostics("en")

    assert steps[-1] == "diag_step_log"
    assert steps.count("diag_step_log") == 1


def test_service_log_snapshot_counts_and_tails_without_writing(tmp_path) -> None:
    path = tmp_path / "service.log"
    lines = [f"2026-07-31 10:00:00 INFO line {i}" for i in range(205)]
    lines[3] = "2026-07-31 10:00:00 WARNING camera delayed"
    lines[4] = "2026-07-31 10:00:00 ERROR pipe failed"
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8") + b"bad:\xff\n")
    before = path.read_bytes()

    snapshot = diagnostics.read_service_log(path)

    assert snapshot.warnings == 1
    assert snapshot.errors == 1
    assert len(snapshot.tail.splitlines()) == 200
    assert "line 0" not in snapshot.tail
    assert "bad:�" in snapshot.tail
    assert path.read_bytes() == before


def test_log_check_handles_missing_empty_and_read_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(diagnostics.config, "DATA_DIR", tmp_path)
    report = _report()
    diagnostics._check_log(report, "en")
    assert report.items[0].status == diagnostics.STATUS_FAIL
    assert "Log not found" in report.items[0].detail

    path = tmp_path / "service.log"
    path.write_text("", encoding="utf-8")
    report = _report()
    diagnostics._check_log(report, "en")
    assert report.items[0].status == diagnostics.STATUS_OK
    assert report.service_log is not None
    assert report.service_log.tail == ""

    monkeypatch.setattr(diagnostics, "read_service_log", lambda _path: (_ for _ in ()).throw(
        PermissionError("denied")
    ))
    report = _report()
    diagnostics._check_log(report, "en")
    assert report.items[0].status == diagnostics.STATUS_FAIL
    assert "denied" in report.items[0].detail


def test_redact_diagnostics_text_hides_users_and_credentials() -> None:
    text = "owen unlocked for Alice password=hunter2 pwd: 1234 secret = token normal text"

    redacted = diagnostics.redact_diagnostics_text(text, ["owen", "Alice"])

    assert "owen" not in redacted
    assert "Alice" not in redacted
    assert "hunter2" not in redacted
    assert "1234" not in redacted
    assert "token" not in redacted
    assert "normal text" in redacted
    assert redacted.count("<redacted>") == 3


def test_export_bundle_uses_whitelist_and_redacts(tmp_path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "service.log").write_text(
        "2026 INFO user=owen password=hunter2\n", encoding="utf-8"
    )
    (data / "service.log.1").write_text("Alice secret: token\n", encoding="utf-8")
    (data / "faces.dat").write_bytes(b"private-face-store")
    (data / "avatar.png").write_bytes(b"private-image")
    (data / "settings.txt").write_text("private-setting", encoding="utf-8")
    report = _report()
    report.items.append(DiagnosticItem("Store", diagnostics.STATUS_OK, "owen and Alice"))

    target = diagnostics.export_diagnostic_bundle(
        tmp_path / "bundle", report, "en", data, ["Alice"]
    )

    assert target.name == "bundle.zip"
    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == {
            "diagnostics.txt", "logs/service.log", "logs/service.log.1"
        }
        combined = "\n".join(
            archive.read(name).decode("utf-8") for name in archive.namelist()
        )
    assert "owen" not in combined
    assert "Alice" not in combined
    assert "hunter2" not in combined
    assert "token" not in combined
    assert "private-face-store" not in combined
    assert "private-image" not in combined
    assert "private-setting" not in combined


def test_export_bundle_requires_current_log(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        diagnostics.export_diagnostic_bundle(tmp_path / "bundle.zip", _report(), data_dir=tmp_path)


def test_cp_registry_error_becomes_diagnostic_item(monkeypatch, tmp_path) -> None:
    def open_key(*args, **kwargs):
        raise FileNotFoundError("missing key")

    fake_winreg = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE=1,
        HKEY_CLASSES_ROOT=2,
        OpenKey=open_key,
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setattr(diagnostics.config, "CP_DLL", tmp_path / "FaceHelloCP.dll")
    report = _report()

    diagnostics._check_cp(report, "en")

    assert report.items[0].status == diagnostics.STATUS_FAIL
    assert "missing key" in report.items[0].detail

