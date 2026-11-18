from __future__ import annotations

import pytest
import win32service

from face_hello import config
from face_hello import win_service


def test_expected_service_recovery_is_bounded() -> None:
    actions, non_crash_failures = win_service.expected_service_recovery()

    assert actions == {
        "ResetPeriod": 86_400,
        "RebootMsg": None,
        "Command": None,
        "Actions": (
            (win32service.SC_ACTION_RESTART, 60_000),
            (win32service.SC_ACTION_RESTART, 120_000),
            (win32service.SC_ACTION_NONE, 0),
        ),
    }
    assert non_crash_failures is True
    assert win_service.service_recovery_matches(actions, non_crash_failures)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ResetPeriod", 60),
        (
            "Actions",
            (
                (win32service.SC_ACTION_RESTART, 60_000),
                (win32service.SC_ACTION_RESTART, 120_000),
            ),
        ),
    ],
)
def test_service_recovery_matches_rejects_changed_policy(field, value) -> None:
    actions, non_crash_failures = win_service.expected_service_recovery()
    changed = dict(actions)
    changed[field] = value

    assert not win_service.service_recovery_matches(changed, non_crash_failures)
    assert not win_service.service_recovery_matches(actions, False)


def test_configure_service_recovery_writes_policy_and_closes_handles(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        win32service,
        "OpenSCManager",
        lambda machine, database, access: calls.append(
            ("open_scm", machine, database, access)
        )
        or "scm",
    )
    monkeypatch.setattr(
        win32service,
        "OpenService",
        lambda scm, name, access: calls.append(("open_service", scm, name, access))
        or "service",
    )
    monkeypatch.setattr(
        win32service,
        "ChangeServiceConfig2",
        lambda service, level, value: calls.append(
            ("change", service, level, value)
        ),
    )
    monkeypatch.setattr(
        win32service,
        "CloseServiceHandle",
        lambda handle: calls.append(("close", handle)),
    )

    win_service.configure_service_recovery()

    expected_actions, expected_flag = win_service.expected_service_recovery()
    assert calls == [
        ("open_scm", None, None, win32service.SC_MANAGER_CONNECT),
        (
            "open_service",
            "scm",
            config.SERVICE_NAME,
            win32service.SERVICE_CHANGE_CONFIG | win32service.SERVICE_START,
        ),
        (
            "change",
            "service",
            win32service.SERVICE_CONFIG_FAILURE_ACTIONS,
            expected_actions,
        ),
        (
            "change",
            "service",
            win32service.SERVICE_CONFIG_FAILURE_ACTIONS_FLAG,
            expected_flag,
        ),
        ("close", "service"),
        ("close", "scm"),
    ]


def test_configure_service_recovery_closes_handles_on_failure(monkeypatch) -> None:
    closed = []
    monkeypatch.setattr(win32service, "OpenSCManager", lambda *_args: "scm")
    monkeypatch.setattr(win32service, "OpenService", lambda *_args: "service")
    monkeypatch.setattr(
        win32service,
        "ChangeServiceConfig2",
        lambda *_args: (_ for _ in ()).throw(OSError("failed")),
    )
    monkeypatch.setattr(
        win32service, "CloseServiceHandle", lambda handle: closed.append(handle)
    )

    with pytest.raises(OSError, match="failed"):
        win_service.configure_service_recovery()

    assert closed == ["service", "scm"]
