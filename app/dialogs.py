from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from face_hello import config
from face_hello.i18n import tr


def label_presets() -> list[str]:
    return [
        tr("label_front"),
        tr("label_left"),
        tr("label_right"),
        tr("label_night"),
        tr("label_glasses_on"),
        tr("label_glasses_off"),
        tr("label_side"),
    ]


def hotkey_text(value: str) -> str:
    value = str(value or "").upper()
    if value == "SPACE":
        return tr("hotkey_space")
    if value == "ENTER":
        return tr("hotkey_enter")
    return value or tr("hotkey_none")


class TemplateLabelDialog(QDialog):
    def __init__(self, default_label: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("template_label_title"))
        self.resize(340, 120)

        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.addItems(label_presets())
        self.combo.setCurrentText(
            (default_label or "").strip()[:config.TEMPLATE_LABEL_MAX_LENGTH]
        )
        if self.combo.lineEdit() is not None:
            self.combo.lineEdit().setMaxLength(config.TEMPLATE_LABEL_MAX_LENGTH)

        hint = QLabel(tr("template_label_prompt"))
        hint.setWordWrap(True)
        save_btn = QPushButton(tr("save_label"))
        save_btn.setObjectName("accent")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton(tr("cancel_btn"))
        cancel_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(hint)
        layout.addWidget(self.combo)
        layout.addLayout(btn_row)

    def label(self) -> str:
        return self.combo.currentText().strip()[:config.TEMPLATE_LABEL_MAX_LENGTH]

    @staticmethod
    def prompt(parent, default_label: str = "") -> str | None:
        dlg = TemplateLabelDialog(default_label, parent)
        if dlg.exec() == QDialog.Accepted:
            return dlg.label()
        return None


class HotkeyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = ""
        self.setWindowTitle(tr("hotkey_capture_title"))
        self.prompt = QLabel(tr("hotkey_capture_prompt"))
        self.prompt.setAlignment(Qt.AlignCenter)
        self.prompt.setMinimumWidth(280)

        cancel_btn = QPushButton(tr("cancel_btn"))
        cancel_btn.setFocusPolicy(Qt.NoFocus)
        cancel_btn.installEventFilter(self)
        cancel_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(self.prompt)
        layout.addLayout(btn_row)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFocus()

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.KeyPress:
            return self._handle_key(event)
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:
        if not self._handle_key(event):
            super().keyPressEvent(event)

    def _handle_key(self, event) -> bool:
        key = int(event.key())
        value = ""
        if key == int(Qt.Key_Space):
            value = "SPACE"
        elif key in (int(Qt.Key_Return), int(Qt.Key_Enter)):
            value = "ENTER"
        elif int(Qt.Key_A) <= key <= int(Qt.Key_Z):
            value = chr(ord("A") + key - int(Qt.Key_A))
        elif int(Qt.Key_0) <= key <= int(Qt.Key_9):
            value = chr(ord("0") + key - int(Qt.Key_0))

        if value:
            self.value = value
            self.accept()
            return True
        if key == int(Qt.Key_Escape):
            self.reject()
            return True
        self.prompt.setText(tr("hotkey_capture_invalid"))
        return True
