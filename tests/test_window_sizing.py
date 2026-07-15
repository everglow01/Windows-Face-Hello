from __future__ import annotations

from PySide6.QtCore import QSize

from app.main import _initial_window_size


class _Layout:
    def __init__(self) -> None:
        self.activated = False

    def activate(self) -> None:
        self.activated = True


class _Window:
    def __init__(self, hint: QSize) -> None:
        self.hint = hint
        self.polished = False
        self.window_layout = _Layout()

    def ensurePolished(self) -> None:
        self.polished = True

    def layout(self) -> _Layout:
        return self.window_layout

    def sizeHint(self) -> QSize:
        return self.hint


def test_initial_window_size_expands_to_layout_hint() -> None:
    window = _Window(QSize(1198, 742))

    size = _initial_window_size(window, QSize(1180, 720))

    assert window.polished
    assert window.window_layout.activated
    assert size == QSize(1198, 742)


def test_initial_window_size_keeps_larger_preferred_size() -> None:
    window = _Window(QSize(1100, 700))

    size = _initial_window_size(window, QSize(1180, 720))

    assert size == QSize(1180, 720)
