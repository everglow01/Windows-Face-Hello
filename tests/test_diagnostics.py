from __future__ import annotations

import types
import sys
from datetime import datetime

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

