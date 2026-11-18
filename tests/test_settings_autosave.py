from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

from app import main  # noqa: E402
from face_hello import config  # noqa: E402
from face_hello.store import FaceStore  # noqa: E402


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab(qapp, tmp_path, monkeypatch):
    mirrors = {}

    def record(key, value):
        mirrors[key] = value
        return True

    monkeypatch.setattr(main, "save_hotkey_mirror", lambda hk: record("hotkey", hk))
    monkeypatch.setattr(main, "save_auth_scope_mirror", lambda *flags: record("scope", flags))
    monkeypatch.setattr(main, "save_unlock_start_mode_mirror", lambda value: record("mode", value))
    store = FaceStore(tmp_path / "faces.dat").load()
    widget = main.SettingsTab(store)
    widget.mirrors = mirrors
    yield widget
    widget._autosave_timer.stop()
    widget.deleteLater()


def _saved(tab) -> dict:
    return FaceStore(tab.store.path).load().get_settings()


def test_change_is_saved_automatically_after_debounce(tab):
    tab.lockout_fails_spin.setValue(9)
    tab.liveness_check.setChecked(False)
    tab.start_mode.buttons["manual"].click()
    assert tab._autosave_timer.isActive()  # 连续修改只排程一次写盘
    assert not tab.store.path.exists()

    tab._autosave_timer.timeout.emit()

    saved = _saved(tab)
    assert saved["lockout_max_fails"] == 9
    assert saved["liveness_enabled"] is False
    assert saved["unlock_start_mode"] == "manual"
    assert tab.mirrors["hotkey"] == ""
    assert tab.mirrors["mode"] == "manual"
    assert tab.autosave_status.text() == main.tr("settings_autosaved")


def test_hotkey_change_schedules_save(tab):
    tab.unlock_hotkey = "SPACE"
    assert tab._save()
    tab._clear_hotkey()
    assert tab._autosave_timer.isActive()
    tab._autosave_timer.timeout.emit()
    assert _saved(tab)["unlock_hotkey"] == ""


def test_save_failure_is_reported_inline(tab, monkeypatch):
    def boom():
        raise PermissionError("denied")

    tab.face_unlock_check.setChecked(False)
    monkeypatch.setattr(tab.store, "save", boom)
    assert not tab._save()
    assert tab.autosave_status.text() == main.tr("settings_save_failed")
    assert tab.store.get_settings()["face_unlock_enabled"] == config.DEFAULTS["face_unlock_enabled"]
    assert not tab.mirrors


def test_failed_mirror_sync_keeps_saved_settings_and_retries(tab, monkeypatch):
    tab.start_mode.buttons["manual"].click()
    with monkeypatch.context() as failing:
        failing.setattr(main, "save_unlock_start_mode_mirror", lambda _mode: False)
        assert not tab._save()
    assert tab.autosave_status.text() == main.tr("unlock_start_sync_failed")
    assert _saved(tab)["unlock_start_mode"] == "manual"

    monkeypatch.setattr(tab.store, "save", lambda: pytest.fail("镜像重试不应再写数据文件"))
    assert tab._save()
    assert tab.mirrors["mode"] == "manual"


def test_pending_autosave_does_not_capture_unfinished_stream_edit(tab):
    tab.camera_mode.buttons["stream"].click()
    tab.camera_url_edit.setText("rtsp://old.invalid/stream")
    assert tab._save()
    tab.lockout_fails_spin.setValue(9)
    tab.camera_url_edit.setText("rtsp://camera.invalid/stream")
    tab._autosave_timer.timeout.emit()
    assert _saved(tab)["lockout_max_fails"] == 9
    assert _saved(tab)["camera_url"] == "rtsp://old.invalid/stream"

    tab.camera_url_edit.editingFinished.emit()
    tab._autosave_timer.timeout.emit()
    assert _saved(tab)["camera_url"] == "rtsp://camera.invalid/stream"


@pytest.mark.parametrize("url", ["rtsp://camera.invalid/stream", "http://[broken/video"])
def test_close_flushes_pending_settings_or_confirms_discard(tab, monkeypatch, url):
    window = main.MainWindow.__new__(main.MainWindow)
    QWidget.__init__(window)
    window._close_ready = window._closing = False
    window._active_workers = lambda: []
    window.settings_tab = tab
    tab.camera_mode.buttons["stream"].click()
    tab.lockout_fails_spin.setValue(9)
    tab.camera_url_edit.setText(url)
    assert tab._autosave_timer.isActive()
    event = QCloseEvent()
    prompts = []

    def refuse_discard(_window, _title, text, *_args):
        prompts.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", refuse_discard)
    window.closeEvent(event)
    assert not tab._autosave_timer.isActive()
    if url.startswith("rtsp:"):
        assert event.isAccepted() and not prompts
        assert _saved(tab)["lockout_max_fails"] == 9
        assert _saved(tab)["camera_url"] == url
    else:
        assert not event.isAccepted()
        assert prompts == [main.tr("settings_close_unsaved")]
        assert not tab.store.path.exists()


def test_reset_restores_defaults_and_saves(tab, monkeypatch):
    tab.lockout_fails_spin.setValue(9)
    tab.face_unlock_check.setChecked(False)
    tab.start_mode.buttons["manual"].click()
    tab.camera_url_edit.setText("rtsp://camera.invalid/stream")
    tab.camera_mode.buttons["stream"].click()
    tab.camera_user_edit.setText("test-user")
    tab.camera_pass_edit.setText("test-password")
    tab.unlock_hotkey = "SPACE"
    tab._save()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
    )

    tab._reset_settings()

    saved = _saved(tab)
    for key in tab._bindings:
        assert saved[key] == config.DEFAULTS[key], key
    assert saved["unlock_hotkey"] == config.DEFAULTS["unlock_hotkey"]
    assert tab.mirrors["mode"] == config.DEFAULTS["unlock_start_mode"]
    assert not tab._autosave_timer.isActive()


def test_reset_cancelled_keeps_settings(tab, monkeypatch):
    tab.lockout_fails_spin.setValue(9)
    tab._save()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.No
    )

    tab._reset_settings()

    assert _saved(tab)["lockout_max_fails"] == 9

def test_switch_camera_source_preserves_stream_and_uses_selected_device(tab):
    tab.camera_mode.buttons["stream"].click()
    assert not tab._save()  # Never substitute the local camera for an empty stream.
    tab.camera_url_edit.setText("rtsp://camera.invalid/live")
    tab.camera_user_edit.setText("alex")
    tab.camera_pass_edit.setText("test")
    assert tab._save()
    assert main.camera_source(_saved(tab)) == "rtsp://alex:test@camera.invalid/live"
    tab.camera_mode.buttons["local"].click()
    tab.camera_spin.setValue(2)
    assert tab._save()
    saved = _saved(tab)
    assert main.camera_source(saved) == 2
    assert saved["camera_url"] == "rtsp://camera.invalid/live"
    reopened = main.SettingsTab(FaceStore(tab.store.path).load())
    assert reopened.camera_mode.value() == "local"
    reopened.camera_mode.buttons["stream"].click()
    assert main.camera_source(reopened._read_settings()) == "rtsp://alex:test@camera.invalid/live"
    reopened._autosave_timer.stop()
    reopened.deleteLater()
