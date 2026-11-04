"""管理台对串流来源的防护:无效 URL 不让按钮卡死、含凭据的 URL 随内容变化遮蔽。

用 offscreen 平台跑真实的 Qt 控件,不开摄像头、不加载模型。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox  # noqa: E402

from app import main as app_main  # noqa: E402
from conftest import make_store, unit_vec  # noqa: E402

_BAD_URL = "http://[broken/video"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def warnings(monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text, *a, **k: shown.append(text))
    return shown


def _fail_if_worker_created(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("无效来源不应创建 worker")

    for name in ("EnrollWorker", "AuthWorker", "SimilarityMonitorWorker", "CameraTestWorker"):
        monkeypatch.setattr(app_main, name, boom)


def test_enroll_with_invalid_url_keeps_buttons_usable(qapp, tmp_path, monkeypatch, warnings):
    _fail_if_worker_created(monkeypatch)
    store = make_store(tmp_path, camera_url=_BAD_URL, camera_url_username="me",
                       camera_url_password="hunter2")
    tab = app_main.EnrollTab(object(), store)
    tab.name_edit.setText("me")

    tab._begin(append=False)
    tab._begin(append=True)

    assert tab.start_btn.isEnabled() and tab.append_btn.isEnabled()
    assert len(warnings) == 2
    assert all("hunter2" not in w and "broken" not in w for w in warnings)


def test_auth_and_monitor_with_invalid_url_keep_buttons_usable(qapp, tmp_path, monkeypatch,
                                                                warnings):
    _fail_if_worker_created(monkeypatch)
    store = make_store(tmp_path, camera_url=_BAD_URL, camera_url_username="me")
    store.add_profile("me", unit_vec(1.0))
    tab = app_main.AuthTab(object(), store)

    tab._start()
    tab._toggle_monitor()

    assert tab.start_btn.isEnabled() and tab.monitor_btn.isEnabled()
    assert tab.monitor is None
    assert len(warnings) == 2


def test_settings_camera_test_and_save_reject_invalid_url(qapp, tmp_path, monkeypatch, warnings):
    _fail_if_worker_created(monkeypatch)
    store = make_store(tmp_path)
    tab = app_main.SettingsTab(store)
    tab.camera_url_edit.setText(_BAD_URL)
    tab.camera_user_edit.setText("me")

    tab._test_camera()
    assert tab.camera_test_btn.isEnabled()

    monkeypatch.setattr(store, "save", lambda: pytest.fail("无效 URL 不应落盘"))
    tab._save()
    assert store.get_settings()["camera_url"] == ""
    assert len(warnings) == 2


def test_settings_url_echo_follows_content(qapp, tmp_path):
    tab = app_main.SettingsTab(make_store(tmp_path))
    edit = tab.camera_url_edit
    assert edit.echoMode() == QLineEdit.Normal

    edit.setText("http://user:secret@10.0.0.5:8080/video")  # 首次为空、之后粘贴含密码的 URL
    assert edit.echoMode() == QLineEdit.Password

    edit.setText("http://10.0.0.5:8080/video?token=abc")
    assert edit.echoMode() == QLineEdit.Password

    edit.setText("http://10.0.0.5:8080/video")
    assert edit.echoMode() == QLineEdit.Normal


def test_settings_url_with_saved_credentials_starts_masked(qapp, tmp_path):
    store = make_store(tmp_path, camera_url="http://user:secret@10.0.0.5/video")
    tab = app_main.SettingsTab(store)
    assert tab.camera_url_edit.echoMode() == QLineEdit.Password


@pytest.mark.parametrize("url", [
    "http://user:FAKE_PASSWORD@host/video",
    "http://host/video?token=FAKE_TOKEN",
    "http://host/video#FAKE_FRAGMENT",
])
def test_settings_url_typing_preserves_text_and_masks_secrets(qapp, tmp_path, url):
    tab = app_main.SettingsTab(make_store(tmp_path))
    tab.show()
    edit = tab.camera_url_edit
    try:
        edit.setFocus()
        qapp.processEvents()
        QTest.keyClicks(edit, url)
        assert edit.text() == url

        tab.camera_spin.setFocus()
        qapp.processEvents()
        assert edit.text() == url
        assert "FAKE_" not in edit.displayText()

        edit.setFocus()
        edit.end(False)
        qapp.processEvents()
        QTest.keyClicks(edit, "x")
        assert edit.text() == url + "x"

        edit.selectAll()
        QTest.keyClicks(edit, "http://host/video")
        assert edit.text() == "http://host/video"
        assert edit.echoMode() == QLineEdit.Normal
    finally:
        tab.close()
        tab.deleteLater()
