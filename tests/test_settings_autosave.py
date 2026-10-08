from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app import main  # noqa: E402
from face_hello import config  # noqa: E402
from face_hello.store import FaceStore  # noqa: E402


@pytest.fixture
def tab(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    mirrors = {}
    monkeypatch.setattr(main, "save_hotkey_mirror", lambda hk: mirrors.__setitem__("hotkey", hk))
    monkeypatch.setattr(
        main, "save_auth_scope_mirror",
        lambda *flags: mirrors.__setitem__("scope", flags),
    )
    store = FaceStore(tmp_path / "faces.dat").load()
    widget = main.SettingsTab(store)
    widget.mirrors = mirrors
    yield widget
    widget.deleteLater()


def _saved(tab) -> dict:
    return FaceStore(tab.store.path).load().get_settings()


def test_change_is_saved_automatically_after_debounce(tab):
    tab.lockout_fails_spin.setValue(9)
    tab.liveness_check.setChecked(False)
    assert tab._autosave_timer.isActive()  # 连续修改只排程一次写盘
    assert not tab.store.path.exists()

    tab._autosave_timer.timeout.emit()

    saved = _saved(tab)
    assert saved["lockout_max_fails"] == 9
    assert saved["liveness_enabled"] is False
    assert tab.mirrors["hotkey"] == ""
    assert tab.autosave_status.text() == main.tr("settings_autosaved")


def test_hotkey_change_schedules_save(tab):
    tab._clear_hotkey()
    assert tab._autosave_timer.isActive()


def test_save_failure_is_reported_inline(tab, monkeypatch):
    def boom():
        raise PermissionError("denied")

    monkeypatch.setattr(tab.store, "save", boom)
    tab._save()
    assert "denied" in tab.autosave_status.text()
    assert "hotkey" not in tab.mirrors  # 没写盘成功就不同步镜像


def test_reset_restores_defaults_and_saves(tab, monkeypatch):
    tab.lockout_fails_spin.setValue(9)
    tab.face_unlock_check.setChecked(False)
    tab.unlock_hotkey = "SPACE"
    tab._save()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
    )

    tab._reset_settings()

    saved = _saved(tab)
    for key in tab._bindings:
        assert saved[key] == pytest.approx(config.DEFAULTS[key]), key
    assert saved["unlock_hotkey"] == config.DEFAULTS["unlock_hotkey"]
    assert not tab._autosave_timer.isActive()


def test_reset_cancelled_keeps_settings(tab, monkeypatch):
    tab.lockout_fails_spin.setValue(9)
    tab._save()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.No
    )

    tab._reset_settings()

    assert _saved(tab)["lockout_max_fails"] == 9
