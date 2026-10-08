from __future__ import annotations

from face_hello import config
from face_hello.i18n import hotkey_mirror_text, save_hotkey_mirror


def test_hotkey_mirror_text_normalizes_single_key():
    assert hotkey_mirror_text(" space ") == "SPACE"
    assert hotkey_mirror_text("") == ""


def test_any_input_mode_overrides_hotkey():
    # 任意输入与单键热键互斥:开启时 CP 只看到 "ANY",原热键被忽略
    assert hotkey_mirror_text("SPACE", any_input=True) == "ANY"
    assert hotkey_mirror_text("", any_input=True) == "ANY"


def test_save_hotkey_mirror_writes_any(tmp_path, monkeypatch):
    target = tmp_path / "hotkey.txt"
    monkeypatch.setattr(config, "HOTKEY_FILE", target)
    save_hotkey_mirror("A", any_input=True)
    assert target.read_text(encoding="utf-8").strip() == "ANY"
    save_hotkey_mirror("A")
    assert target.read_text(encoding="utf-8").strip() == "A"
