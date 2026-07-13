"""FaceHello 管理台入口。

锁屏解锁由已部署的 C++ Credential Provider 与 LocalSystem 认证服务完成。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QPainter, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.workers import (
    AuthWorker,
    CameraTestWorker,
    DiagnosticsWorker,
    EnrollWorker,
    SimilarityMonitorWorker,
    UpdateCheckWorker,
    UpdateDownloadWorker,
    WarmupWorker,
)
from app.dialogs import HotkeyDialog, TemplateLabelDialog, hotkey_text as _hotkey_text
from app.widgets import (
    DANGER,
    PREVIEW_H,
    PREVIEW_W,
    SUCCESS,
    CaptionButton,
    ResizeHandle,
    SimilarityHistogram,
    preview_label as _preview_label,
    show_frame as _show_frame,
)
from face_hello.diagnostics import DiagnosticReport, status_label
from face_hello import config, cred_vault, probes
from face_hello.auth import AuthResult
from face_hello.detector import FaceDetector
from face_hello.i18n import save_hotkey_mirror, save_lang_mirror, set_lang, tr
from face_hello.store import FaceStore
from face_hello.updater import UpdateCandidate, UpdateError, UpdateErrorCode, verify_installer
from face_hello.version import display_version, get_build_info

WARN = "#9A5B16"
_CONSOLE_MUTEX = None

# 大号活体提示文字的基础样式(颜色随结果在内联追加)
_INSTR_BASE = "font-size:18px;font-weight:600;padding:8px;color:#2F261F;"

# Win11 Fluent 浅色主题
FLUENT_QSS = """
* {
    font-family: "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI",
                 "Microsoft YaHei", sans-serif;
    font-size: 14px;
    color: #2F261F;
}
QWidget { background-color: #F7F2EA; }

QPushButton {
    background-color: #FFFCF7;
    border: 1px solid #D9CABB;
    border-radius: 6px;
    padding: 7px 16px;
}
QPushButton:hover { background-color: #F7EDE2; border-color: #CDB8A6; }
QPushButton:pressed { background-color: #EEDFD0; border-color: #B99D87; }
QPushButton:focus { border: 1px solid #B99D87; }
QPushButton:default { background-color: #FFF7EF; border: 1px solid #C78F72; }
QPushButton:default:pressed { background-color: #EEDFD0; border-color: #B99D87; }
QPushButton:disabled { background-color: #F0E8DF; color: #A99C8F; border-color: #E8DED3; }

QPushButton#accent {
    background-color: #B45E3C;
    border: 1px solid #B45E3C;
    color: #FFF9F2;
    font-weight: 600;
}
QPushButton#accent:hover { background-color: #C06B47; border-color: #C06B47; }
QPushButton#accent:pressed { background-color: #9E4D30; border-color: #9E4D30; }
QPushButton#accent:focus { border: 1px solid #7F3B24; }
QPushButton#accent:default { background-color: #B45E3C; border: 1px solid #7F3B24; }
QPushButton#accent:default:pressed { background-color: #9E4D30; border-color: #7F3B24; }
QPushButton#accent:disabled { background-color: #D9B7A6; border-color: #D9B7A6; color: #FFF1E9; }

QLineEdit, QSpinBox, QDoubleSpinBox {
    background: #FFFFFF;
    border: 1px solid #D1D1D1;
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: #B45E3C;
    selection-color: #FFF9F2;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #B45E3C; }

/* 自定义边框后必须显式给上下按钮几何,否则点击区域塌陷、点上三角会落到输入框上 */
QSpinBox, QDoubleSpinBox { padding-right: 22px; }
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid #D9CABB;
    border-top-right-radius: 6px;
    background: #F3E9DE;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 20px;
    border-left: 1px solid #D9CABB;
    border-bottom-right-radius: 6px;
    background: #F3E9DE;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: #E9D8C8; }
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed { background: #DFC6B3; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(__UP_ARROW__); }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(__DOWN_ARROW__); }

QTableWidget {
    background: #FFFFFF;
    border: 1px solid #E5E5E5;
    border-radius: 8px;
    gridline-color: #F0F0F0;
}
QTableWidget::item { padding: 6px; }
QTableWidget::item:selected { background: #F3DCCB; color: #2F261F; }
QHeaderView::section {
    background: #FAFAFA;
    color: #5A5A5A;
    border: none;
    border-bottom: 1px solid #E5E5E5;
    padding: 8px;
    font-weight: 600;
}
QTableCornerButton::section { background: #FAFAFA; border: none; }

QCheckBox { spacing: 8px; }

QLabel#h2 {
    font-size: 15px;
    font-weight: 600;
    color: #1A1A1A;
}
QLabel#hint { color: #5A5A5A; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #C9C9C9; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #B0B0B0; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QWidget#sideBar {
    background: #EFE4D8;
    border: 1px solid #E1D0BE;
    border-radius: 8px;
}
QWidget#contentPanel {
    background: #FFFCF7;
    border: 1px solid #E6D8C9;
    border-radius: 8px;
}
QWidget#rootWindow {
    background: transparent;
}
QWidget#resizeHandle {
    background: transparent;
}
QWidget#windowShell {
    background: #F7F2EA;
    border: 1px solid #DDCBB8;
    border-radius: 12px;
}
QPushButton:checked { background-color: #FFF7EF; border-color: #E4C5B2; }
QPushButton:checked:pressed { background-color: #EEDFD0; border-color: #B99D87; }
QPushButton#navButton {
    background: transparent;
    border: 1px solid transparent;
    color: #5E5146;
    text-align: left;
    padding: 9px 12px;
    font-weight: 500;
}
QPushButton#navButton:hover {
    background: #F1E6DA;
    border-color: #E2D2C3;
}
QPushButton#navButton:pressed {
    background: #E8D8C8;
    border-color: #CDB8A6;
}
QPushButton#navButton:checked {
    background: #FFF7EF;
    border-color: #E4C5B2;
    color: #9E4D30;
    font-weight: 600;
}
QPushButton#navButton:checked:pressed {
    background: #EEDFD0;
    border-color: #B99D87;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #FFFCF7;
    border: 1px solid #D9CABB;
    selection-background-color: #B45E3C;
    selection-color: #FFF9F2;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #B45E3C;
}
QTableWidget {
    background: #FFFCF7;
    border: 1px solid #E6D8C9;
    gridline-color: #EFE3D6;
}
QTableWidget::item:selected { background: #F3DCCB; color: #2F261F; }
QHeaderView::section {
    background: #F5EADF;
    color: #6A5B4E;
    border-bottom: 1px solid #E6D8C9;
}
QLabel#h2 { color: #2F261F; }
QLabel#brand {
    font-size: 22px;
    font-weight: 700;
    color: #2F261F;
    background: transparent;
}
QLabel#hint, QLabel#sideHint { color: #716457; }
QLabel#sideHint {
    font-size: 12px;
    background: transparent;
}
QComboBox#sideCombo {
    background: #EFE4D8;
    border: 1px solid #D8C5B3;
    padding: 5px 28px 5px 8px;
}
QComboBox#sideCombo:hover {
    background: #F3E8DC;
    border-color: #CDB8A6;
}
QComboBox#sideCombo::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border: none;
    background: transparent;
}
QComboBox#sideCombo::down-arrow {
    image: url(__COMBO_ARROW__);
    width: 10px;
    height: 10px;
}
QWidget#titleBar {
    background: transparent;
}
QPushButton#windowButton, QPushButton#windowCloseButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 0;
    min-width: 46px;
    min-height: 32px;
    color: #6A5B4E;
}
QPushButton#windowButton:hover {
    background: #EDE1D5;
    border-color: transparent;
}
QPushButton#windowButton:pressed {
    background: #E2D0BF;
    border-color: transparent;
}
QPushButton#windowCloseButton:hover {
    background: #C75B3A;
    border-color: #C75B3A;
    color: #FFF9F2;
}
QPushButton#windowCloseButton:pressed {
    background: #9E4D30;
    border-color: #9E4D30;
    color: #FFF9F2;
}
QProgressBar {
    background: #F1E6DA;
    border: 1px solid #E1D0BE;
    border-radius: 5px;
    height: 10px;
}
QProgressBar::chunk {
    background: #B45E3C;
    border-radius: 5px;
}
QScrollBar::handle:vertical { background: #CDB8A6; }
QScrollBar::handle:vertical:hover { background: #B99D87; }
"""


def _make_arrow(path: str, up: bool) -> None:
    """画一个小三角箭头 PNG 到 path(QSS 接管 spinbox 后默认箭头不再绘制,自带一个)。"""
    pm = QPixmap(12, 12)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#5A5A5A"))
    p.setPen(Qt.NoPen)
    if up:
        tri = QPolygon([QPoint(2, 8), QPoint(10, 8), QPoint(6, 4)])
    else:
        tri = QPolygon([QPoint(2, 5), QPoint(10, 5), QPoint(6, 9)])
    p.drawPolygon(tri)
    p.end()
    pm.save(path, "PNG")


def _make_combo_arrow(path: str) -> None:
    pm = QPixmap(12, 12)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QColor("#8A6A55")
    p.setPen(pen)
    p.drawLine(3, 5, 6, 8)
    p.drawLine(6, 8, 9, 5)
    p.end()
    pm.save(path, "PNG")


def _themed_qss() -> str:
    """生成箭头图标到临时目录(纯 ASCII 路径),把其路径填进 QSS。"""
    import os
    import tempfile

    tmp = tempfile.gettempdir()
    up = os.path.join(tmp, "facehello_spin_up.png").replace("\\", "/")
    down = os.path.join(tmp, "facehello_spin_down.png").replace("\\", "/")
    combo = os.path.join(tmp, "facehello_combo_down.png").replace("\\", "/")
    _make_arrow(up, True)
    _make_arrow(down, False)
    _make_combo_arrow(combo)
    return (
        FLUENT_QSS
        .replace("__UP_ARROW__", up)
        .replace("__DOWN_ARROW__", down)
        .replace("__COMBO_ARROW__", combo)
    )


def _renewal_days_text(profile) -> str:
    days = profile.days_until_renewal
    if days < 0:
        return tr("renewal_overdue_days", days=-days)
    return tr("renewal_remaining_days", days=days)


class EnrollTab(QWidget):
    def __init__(self, detector: FaceDetector, store: FaceStore):
        super().__init__()
        self.detector = detector
        self.store = store
        self.worker: EnrollWorker | None = None
        self._append = False  # 本次录入是「补录角度」(追加)还是「开始录入」(覆盖)

        self.name_edit = QLineEdit()
        # 预填当前 Windows 账户名:档案名必须等于该账户名,锁屏刷脸才能对上 LSA 密码 + KERB
        self.name_edit.setText(cred_vault.current_user())
        self.name_edit.setPlaceholderText(tr("win_account_name"))
        self.start_btn = QPushButton(tr("start_enroll"))
        self.start_btn.setObjectName("accent")
        self.start_btn.clicked.connect(lambda: self._begin(append=False))
        self.append_btn = QPushButton(tr("add_angle"))  # 同名追加一条模板,覆盖更多角度/光照
        self.append_btn.clicked.connect(lambda: self._begin(append=True))
        self.preview = _preview_label()
        self.status = QLabel(tr("enroll_hint"))
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        self.progress_bar = QProgressBar()  # 只在采到合格帧时推进,给实时反馈
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, self.store.get_settings()["enroll_samples"])
        self.progress_bar.setValue(0)

        # 已录入用户管理(原在「设置与安全」页,挪到此处:录入与管理同处一页)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [tr("col_user"), tr("col_templates"), tr("col_enroll_date"),
             tr("col_days_until_renewal"), tr("col_status")]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMaximumHeight(160)  # 约 3 行高度封顶,超出滚动,不顶坏布局
        self.del_btn = QPushButton(tr("delete_selected"))
        self.del_btn.clicked.connect(self._delete_selected)
        self.manage_btn = QPushButton(tr("manage_templates"))  # 删该用户下单条补录模板
        self.manage_btn.clicked.connect(self._manage_templates)
        users_title = QLabel(tr("enrolled_users"))
        users_title.setObjectName("h2")

        top = QHBoxLayout()
        top.addWidget(QLabel(tr("username_label")))
        top.addWidget(self.name_edit, 1)
        top.addWidget(self.start_btn)
        top.addWidget(self.append_btn)

        del_row = QHBoxLayout()
        del_row.addWidget(self.del_btn)
        del_row.addWidget(self.manage_btn)
        del_row.addStretch(1)  # 按钮不再整行宽

        guide_title = QLabel(tr("enroll_guide_title"))
        guide_title.setObjectName("h2")
        guide_title.setStyleSheet("background:transparent;")
        guide_body = QLabel(tr("enroll_guide_body"))
        guide_body.setObjectName("hint")
        guide_body.setWordWrap(True)
        guide_body.setStyleSheet("background:transparent;")

        left = QVBoxLayout()
        left.setSpacing(10)
        left.addLayout(top)
        left.addWidget(self.preview)
        left.addWidget(self.status)
        left.addWidget(self.progress_bar)

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(users_title)
        right.addWidget(self.table)
        right.addLayout(del_row)
        right.addSpacing(14)
        right.addWidget(guide_title)
        right.addWidget(guide_body)
        right.addStretch(1)

        content = QHBoxLayout()
        content.setSpacing(16)
        content.addLayout(left)
        content.addLayout(right, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.addStretch(1)
        layout.addLayout(content)
        layout.addStretch(1)

        self.refresh()

    def _begin(self, append: bool) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, tr("tip"), tr("enter_username"))
            return
        s = self.store.get_settings()
        samples = s["enroll_samples"]
        self._append = append
        self.start_btn.setEnabled(False)
        self.append_btn.setEnabled(False)
        self.status.setText(tr("opening_camera"))
        self.progress_bar.setRange(0, samples)
        self.progress_bar.setValue(0)
        self.worker = EnrollWorker(self.detector, samples, camera_index=s.get("camera_index", 0),
                                   append=append)
        self.worker.preview.connect(lambda img: _show_frame(self.preview, img))
        self.worker.guidance.connect(self._on_guidance)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_fail)
        self.worker.start()

    def _on_guidance(self, key: str, collected: int, target: int) -> None:
        # 合格/采集态附带计数(进度条已直观显示,文字再点一下进度);其余为静态引导短语
        text = tr(key)
        if key in ("guidance_hold_still", "guidance_captured"):
            text = f"{text} ({collected}/{target})"
        self.status.setText(text)
        self.progress_bar.setValue(collected)

    def _on_done(self, embedding) -> None:
        name = self.name_edit.text().strip()
        default_label = tr("label_side") if self._append else tr("label_front")
        label = TemplateLabelDialog.prompt(self, default_label)
        self.store.add_profile(name, embedding, replace=not self._append, label=label or "")
        self.store.save()
        self.start_btn.setEnabled(True)
        self.append_btn.setEnabled(True)
        self.refresh()  # 录入完即时刷新本页用户表
        if self._append:
            n = sum(1 for p in self.store.list_profiles() if p.name == name)
            self.status.setText(tr("enroll_appended", name=name, n=n))
        else:
            self.status.setText(tr("enrolled_ok", name=name))
            QMessageBox.information(self, tr("done_title"), tr("enroll_success", name=name))

    def _on_fail(self, msg: str) -> None:
        self.status.setText(tr("failed_fmt", msg=msg))
        self.start_btn.setEnabled(True)
        self.append_btn.setEnabled(True)

    def refresh(self) -> None:
        # 按名分组(保序去重):一行一个用户,显示模板数 / 最近录入 / 最快到期 / 状态
        groups: dict[str, list] = {}
        for p in self.store.list_profiles():
            groups.setdefault(p.name, []).append(p)
        self.table.setRowCount(len(groups))
        for r, (name, ps) in enumerate(groups.items()):
            latest = max(ps, key=lambda p: p.enroll_date)   # 最近录入的那条
            next_due = min(ps, key=lambda p: p.days_until_renewal)
            renewal_due = any(p.renewal_due for p in ps)
            status = tr("renewal_due_mark") if renewal_due else tr("renewal_current")
            cells = [name, str(len(ps)), latest.enroll_date.isoformat(),
                     _renewal_days_text(next_due), status]
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(text))

    def _delete_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        name = self.table.item(row, 0).text()
        if QMessageBox.question(self, tr("confirm_title"), tr("delete_user_q", name=name)) == QMessageBox.Yes:
            self.store.remove_profile(name)
            self.store.save()
            self.refresh()

    def _manage_templates(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return  # 同 _delete_selected:未选中用户则不动作
        name = self.table.item(row, 0).text()
        TemplateManagerDialog(self.store, name, self).exec()
        self.refresh()  # 弹窗里可能删过模板,刷新主表模板数


class TemplateManagerDialog(QDialog):
    """管理某用户的多条模板:列出 → 删单条。删到最后一条即移除该用户。"""

    def __init__(self, store: FaceStore, name: str, parent=None):
        super().__init__(parent)
        self.store = store
        self.name = name
        self.setWindowTitle(tr("templates_of", name=name))
        self.resize(560, 280)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [tr("col_index"), tr("col_label"), tr("col_enroll_date"),
             tr("col_days_until_renewal"), tr("col_status")]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        edit_btn = QPushButton(tr("edit_label"))
        edit_btn.clicked.connect(self._edit_label)
        del_btn = QPushButton(tr("delete_template"))
        del_btn.setObjectName("accent")
        del_btn.clicked.connect(self._delete)
        close_btn = QPushButton(tr("close_btn"))
        close_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(self.table)
        layout.addLayout(btn_row)

        self._load()

    def _templates(self) -> list:
        """该用户的模板,按录入顺序(与 store 内部顺序、序号 #1.. 一致)。"""
        return [p for p in self.store.list_profiles() if p.name == self.name]

    def _load(self) -> None:
        ps = self._templates()
        if not ps:
            self.accept()  # 已无模板(删光了)→ 关闭弹窗
            return
        self.table.setRowCount(len(ps))
        for r, p in enumerate(ps):
            status = tr("renewal_due_mark") if p.renewal_due else tr("renewal_current")
            cells = [f"#{r + 1}", p.label or tr("label_empty"),
                     p.enroll_date.isoformat(), _renewal_days_text(p), status]
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.table.selectRow(0)

    def _edit_label(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, tr("tip"), tr("select_template"))
            return
        ps = self._templates()
        if row >= len(ps):
            return
        label = TemplateLabelDialog.prompt(self, ps[row].label)
        if label is None:
            return
        self.store.set_template_label(self.name, row, label)
        self.store.save()
        self._load()

    def _delete(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, tr("tip"), tr("select_template"))
            return
        n = row + 1
        last = len(self._templates()) == 1
        key = "delete_last_template_q" if last else "delete_template_q"
        if QMessageBox.question(self, tr("confirm_title"), tr(key, name=self.name, n=n)) != QMessageBox.Yes:
            return
        self.store.remove_template(self.name, row)  # row == 第 n 条的 0-based 序号
        self.store.save()
        self._load()


class AuthTab(QWidget):
    def __init__(self, detector: FaceDetector, store: FaceStore):
        super().__init__()
        self.detector = detector
        self.store = store
        self.worker: AuthWorker | None = None
        self.monitor: SimilarityMonitorWorker | None = None

        self.start_btn = QPushButton(tr("start_test_unlock"))
        self.start_btn.setObjectName("accent")
        self.start_btn.clicked.connect(self._start)
        self.monitor_btn = QPushButton(tr("live_compare"))
        self.monitor_btn.clicked.connect(self._toggle_monitor)
        self.preview = _preview_label()
        self.instruction = QLabel(tr("auth_idle_hint"))
        self.instruction.setAlignment(Qt.AlignCenter)
        self.instruction.setStyleSheet(_INSTR_BASE)
        self.histogram = SimilarityHistogram()

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.monitor_btn)
        btn_row.addStretch(1)

        panel = QWidget()
        panel.setMaximumWidth(900)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(10)
        panel_layout.addLayout(btn_row)
        panel_layout.addWidget(self.preview, alignment=Qt.AlignCenter)
        panel_layout.addWidget(self.instruction)
        panel_layout.addWidget(self.histogram)

        center = QHBoxLayout()
        center.addStretch(1)
        center.addWidget(panel, 8)
        center.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.addStretch(1)
        layout.addLayout(center)
        layout.addStretch(1)

    def _start(self) -> None:
        if self.store.is_empty():
            QMessageBox.warning(self, tr("tip"), tr("no_enroll_warn"))
            return
        self.start_btn.setEnabled(False)
        self.monitor_btn.setEnabled(False)
        self.instruction.setStyleSheet(_INSTR_BASE)
        self.instruction.setText(tr("preparing"))
        self.worker = AuthWorker(
            self.detector, self.store,
            camera_index=self.store.get_settings().get("camera_index", 0),
        )
        self.worker.preview.connect(lambda img: _show_frame(self.preview, img))
        self.worker.instruction.connect(self.instruction.setText)
        self.worker.finished_result.connect(self._on_result)
        self.worker.failed.connect(self._on_fail)
        self.worker.start()

    def _on_result(self, result: AuthResult) -> None:
        self.start_btn.setEnabled(True)
        self.monitor_btn.setEnabled(True)
        if result.success:
            self.instruction.setStyleSheet(_INSTR_BASE + f"color:{SUCCESS};")
            self.instruction.setText(tr("unlock_pass", name=result.name, sim=result.similarity))
        else:
            self.instruction.setStyleSheet(_INSTR_BASE + f"color:{DANGER};")
            self.instruction.setText(tr("unlock_reject", reason=result.reason))

    def _on_fail(self, msg: str) -> None:
        self.start_btn.setEnabled(True)
        self.monitor_btn.setEnabled(True)
        self.instruction.setText(tr("error_fmt", msg=msg))

    # --- 实时比对(诊断:逐帧相似度直方图,不跑活体/反欺骗,不解锁)---
    def _toggle_monitor(self) -> None:
        if self.monitor is not None:
            self.stop_monitor()
            return
        if self.store.is_empty():
            QMessageBox.warning(self, tr("tip"), tr("no_enroll_warn"))
            return
        self.start_btn.setEnabled(False)
        self.monitor_btn.setText(tr("stop_compare"))
        self.instruction.setStyleSheet(_INSTR_BASE)
        self.instruction.setText(tr("hist_title"))
        self.histogram.set_threshold(self.store.get_settings()["match_threshold"])
        self.histogram.clear()
        self.monitor = SimilarityMonitorWorker(
            self.detector, self.store,
            camera_index=self.store.get_settings().get("camera_index", 0),
            threshold=self.store.get_settings()["match_threshold"],
        )
        self.monitor.preview.connect(lambda img: _show_frame(self.preview, img))
        self.monitor.sample.connect(self.histogram.add_sample)
        self.monitor.failed.connect(self._on_monitor_fail)
        self.monitor.start()

    def stop_monitor(self) -> None:
        if self.monitor is None:
            return
        self.monitor.stop()
        self.monitor.wait()
        self.monitor = None
        self.monitor_btn.setText(tr("live_compare"))
        self.monitor_btn.setEnabled(True)
        self.start_btn.setEnabled(True)

    def _on_monitor_fail(self, msg: str) -> None:
        self.stop_monitor()
        self.instruction.setText(tr("error_fmt", msg=msg))


class SettingsTab(QWidget):
    def __init__(self, store: FaceStore):
        super().__init__()
        self.store = store
        self._update_check: UpdateCheckWorker | None = None
        self._update_download: UpdateDownloadWorker | None = None
        self._update_candidate: UpdateCandidate | None = None
        self._update_installer: Path | None = None

        s = self.store.get_settings()
        self.match_spin = self._dspin(0.0, 1.0, 0.01, s["match_threshold"])
        self.margin_spin = self._dspin(0.0, 0.5, 0.01, s.get("match_margin", 0.05))
        self.yaw_spin = self._dspin(5.0, 45.0, 1.0, s["yaw_threshold_deg"])
        self.blink_spin = QSpinBox()
        self.blink_spin.setRange(1, 5)
        self.blink_spin.setValue(s["required_blinks"])
        self.renewal_spin = QSpinBox()
        self.renewal_spin.setRange(1, 3650)
        self.renewal_spin.setValue(s["renew_days"])
        self.samples_spin = QSpinBox()
        self.samples_spin.setRange(3, 30)
        self.samples_spin.setValue(s["enroll_samples"])
        self.max_templates_spin = QSpinBox()
        self.max_templates_spin.setRange(1, 10)
        self.max_templates_spin.setValue(s.get("max_templates_per_name", 5))
        self.lockout_fails_spin = QSpinBox()
        self.lockout_fails_spin.setRange(0, 20)
        self.lockout_fails_spin.setValue(s.get("lockout_max_fails", 5))
        self.lockout_secs_spin = QSpinBox()
        self.lockout_secs_spin.setRange(0, 600)
        self.lockout_secs_spin.setValue(s.get("lockout_seconds", 30))
        self.camera_spin = QSpinBox()
        self.camera_spin.setRange(0, 10)
        self.camera_spin.setValue(int(s.get("camera_index", 0)))
        self.unlock_hotkey = str(s.get("unlock_hotkey", "") or "").upper()
        self.hotkey_value = QLineEdit(_hotkey_text(self.unlock_hotkey))
        self.hotkey_value.setReadOnly(True)
        self.hotkey_value.setFixedWidth(100)
        self.hotkey_set_btn = QPushButton(tr("hotkey_set_btn"))
        self.hotkey_set_btn.clicked.connect(self._set_hotkey)
        self.hotkey_clear_btn = QPushButton(tr("hotkey_clear_btn"))
        self.hotkey_clear_btn.clicked.connect(self._clear_hotkey)
        for sp in (self.match_spin, self.margin_spin, self.yaw_spin, self.blink_spin,
                   self.renewal_spin, self.samples_spin, self.max_templates_spin,
                   self.lockout_fails_spin, self.lockout_secs_spin, self.camera_spin):
            sp.setFixedWidth(100)  # 窄而对齐,消除右侧大留白
        self.camera_test_btn = QPushButton(tr("camera_test_btn"))
        self.camera_test_btn.clicked.connect(self._test_camera)
        self._cam_test: CameraTestWorker | None = None
        self.liveness_check = QCheckBox(tr("liveness_check"))
        self.liveness_check.setChecked(s["liveness_enabled"])
        self.antispoof_check = QCheckBox(tr("antispoof_check"))
        self.antispoof_check.setChecked(s.get("antispoof_enabled", True))

        save_btn = QPushButton(tr("save_settings"))
        save_btn.setObjectName("accent")
        save_btn.clicked.connect(self._save)

        params_title = QLabel(tr("params_security"))
        params_title.setObjectName("h2")

        # 两列网格:每组一个小标题横跨整行,组内左右各一对「标签 + 控件」
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(4, 1)  # 末列吃掉富余宽度,内容靠左不散开
        r = 0
        grid.addWidget(self.liveness_check, r, 0, 1, 4)
        r += 1
        grid.addWidget(self.antispoof_check, r, 0, 1, 4)
        r += 1

        def group(title_key: str) -> None:
            nonlocal r
            h = QLabel(tr(title_key))
            h.setStyleSheet("color:#666;font-weight:600;margin-top:6px;")
            grid.addWidget(h, r, 0, 1, 4)
            r += 1

        def pair(l1: str, w1, l2: str, w2) -> None:
            nonlocal r
            grid.addWidget(QLabel(tr(l1)), r, 0)
            grid.addWidget(w1, r, 1)
            grid.addWidget(QLabel(tr(l2)), r, 2)
            grid.addWidget(w2, r, 3)
            r += 1

        group("grp_camera")
        grid.addWidget(QLabel(tr("camera_index_label")), r, 0)
        cam_row = QHBoxLayout()
        cam_row.setContentsMargins(0, 0, 0, 0)
        cam_row.setSpacing(8)
        cam_row.addWidget(self.camera_spin)
        cam_row.addWidget(self.camera_test_btn)
        cam_row.addStretch(1)
        cam_w = QWidget()
        cam_w.setLayout(cam_row)
        grid.addWidget(cam_w, r, 1, 1, 3)
        r += 1
        grid.addWidget(QLabel(tr("unlock_hotkey_label")), r, 0)
        hotkey_row = QHBoxLayout()
        hotkey_row.setContentsMargins(0, 0, 0, 0)
        hotkey_row.setSpacing(8)
        hotkey_row.addWidget(self.hotkey_value)
        hotkey_row.addWidget(self.hotkey_set_btn)
        hotkey_row.addWidget(self.hotkey_clear_btn)
        hotkey_row.addStretch(1)
        hotkey_w = QWidget()
        hotkey_w.setLayout(hotkey_row)
        grid.addWidget(hotkey_w, r, 1, 1, 3)
        r += 1
        group("grp_recognition")
        pair("match_threshold_label", self.match_spin, "match_margin_label", self.margin_spin)
        group("grp_liveness")
        pair("yaw_label", self.yaw_spin, "blink_count_label", self.blink_spin)
        group("grp_lockout")
        pair("lockout_fails_label", self.lockout_fails_spin, "lockout_secs_label", self.lockout_secs_spin)
        group("grp_enroll")
        pair("renewal_interval_label", self.renewal_spin, "samples_label", self.samples_spin)
        grid.addWidget(QLabel(tr("max_templates_label")), r, 0)
        grid.addWidget(self.max_templates_spin, r, 1)
        r += 1

        panel = QWidget()
        panel.setMaximumWidth(920)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(10)
        panel_layout.addWidget(params_title)
        panel_layout.addLayout(grid)
        panel_layout.addWidget(save_btn, alignment=Qt.AlignLeft)

        update_title = QLabel(tr("update_title"))
        update_title.setObjectName("h2")
        self.update_status = QLabel(tr("update_current", version=display_version()))
        self.update_status.setWordWrap(True)
        self.update_progress = QProgressBar()
        self.update_progress.setRange(0, 100)
        self.update_progress.hide()
        self.update_btn = QPushButton(tr("update_check"))
        self.update_btn.clicked.connect(self._check_update)
        self.update_download_btn = QPushButton(tr("update_download"))
        self.update_download_btn.clicked.connect(self._download_update)
        self.update_download_btn.hide()
        self.update_install_btn = QPushButton(tr("update_install"))
        self.update_install_btn.clicked.connect(self._install_update)
        self.update_install_btn.hide()
        update_actions = QHBoxLayout()
        update_actions.addWidget(self.update_btn)
        update_actions.addWidget(self.update_download_btn)
        update_actions.addWidget(self.update_install_btn)
        update_actions.addStretch(1)
        panel_layout.addWidget(update_title)
        panel_layout.addWidget(self.update_status)
        panel_layout.addWidget(self.update_progress)
        panel_layout.addLayout(update_actions)

        center = QHBoxLayout()
        center.addStretch(1)
        center.addWidget(panel, 8)
        center.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.addStretch(1)
        layout.addLayout(center)
        layout.addStretch(1)

    @staticmethod
    def _dspin(lo, hi, step, val) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setValue(val)
        return sp

    def _check_update(self) -> None:
        if self._update_check is not None and self._update_check.isRunning():
            return
        self.update_btn.setEnabled(False)
        self.update_download_btn.hide()
        self.update_install_btn.hide()
        self._update_candidate = None
        self._update_installer = None
        self.update_status.setText(tr("update_checking"))
        self._update_check = UpdateCheckWorker()
        self._update_check.checked.connect(self._on_update_checked)
        self._update_check.failed.connect(self._on_update_failed)
        self._update_check.finished.connect(lambda: self.update_btn.setEnabled(True))
        self._update_check.start()

    def _on_update_checked(self, candidate: UpdateCandidate) -> None:
        self._update_candidate = candidate
        if candidate.is_newer is False:
            self.update_status.setText(tr("update_current", version=display_version()))
            return
        if candidate.is_newer is None:
            self.update_status.setText(tr("update_dev_available", version=str(candidate.version)))
        else:
            self.update_status.setText(tr("update_available", version=str(candidate.version)))
        self.update_download_btn.show()

    def _on_update_failed(self, code: str, _detail: str) -> None:
        key = "update_cancelled" if code == UpdateErrorCode.CANCELLED.value else "update_failed"
        self.update_status.setText(tr(key))

    def _download_update(self) -> None:
        if self._update_candidate is None:
            return
        self.update_btn.setEnabled(False)
        self.update_download_btn.setEnabled(False)
        self.update_progress.setValue(0)
        self.update_progress.show()
        self.update_status.setText(tr("update_downloading"))
        self._update_download = UpdateDownloadWorker(self._update_candidate)
        self._update_download.progress.connect(self._on_update_progress)
        self._update_download.downloaded.connect(self._on_update_downloaded)
        self._update_download.failed.connect(self._on_update_failed)
        self._update_download.finished.connect(self._on_update_download_finished)
        self._update_download.start()

    def _on_update_progress(self, downloaded: int, total: int) -> None:
        self.update_progress.setValue(int(downloaded * 100 / total) if total else 0)

    def _on_update_downloaded(self, path: str) -> None:
        self.update_progress.setValue(100)
        self._update_installer = Path(path)
        if config.IS_INSTALLED and get_build_info().signer_sha256:
            self.update_status.setText(tr("update_ready"))
            self.update_install_btn.show()
        else:
            self.update_status.setText(tr("update_downloaded", path=path))
        self.update_download_btn.setText(tr("update_download_again"))

    def _install_update(self) -> None:
        if (
            self._update_installer is None
            or self._update_candidate is None
            or not self._update_installer.is_file()
        ):
            return
        build_info = get_build_info()
        try:
            if not build_info.signer_sha256:
                raise UpdateError(UpdateErrorCode.VERIFY, "release build has no signer pin")
            verify_installer(
                self._update_installer,
                self._update_candidate,
                build_info.signer_sha256,
            )
        except Exception:  # noqa: BLE001 文件/签名平台 API 任一异常都必须 fail closed
            self._update_installer.unlink(missing_ok=True)
            self._update_installer = None
            self.update_install_btn.hide()
            self.update_status.setText(tr("update_failed"))
            return
        import ctypes

        shell_execute = ctypes.windll.shell32.ShellExecuteW
        shell_execute.restype = ctypes.c_void_p
        result = shell_execute(
            None,
            "runas",
            str(self._update_installer),
            f"/FaceHelloParentPID={os.getpid()}",
            str(self._update_installer.parent),
            1,
        )
        if int(result or 0) <= 32:
            QMessageBox.warning(
                self, tr("update_title"), tr("update_launch_failed", msg=int(result or 0))
            )
            return
        window = self.window()
        if window is not None:
            window.close()

    def _on_update_download_finished(self) -> None:
        self.update_btn.setEnabled(True)
        self.update_download_btn.setEnabled(True)

    def _save(self) -> None:
        self.store.update_settings(
            liveness_enabled=self.liveness_check.isChecked(),
            antispoof_enabled=self.antispoof_check.isChecked(),
            match_threshold=self.match_spin.value(),
            match_margin=self.margin_spin.value(),
            yaw_threshold_deg=self.yaw_spin.value(),
            required_blinks=self.blink_spin.value(),
            renew_days=self.renewal_spin.value(),
            enroll_samples=self.samples_spin.value(),
            max_templates_per_name=self.max_templates_spin.value(),
            lockout_max_fails=self.lockout_fails_spin.value(),
            lockout_seconds=self.lockout_secs_spin.value(),
            camera_index=self.camera_spin.value(),
            unlock_hotkey=self.unlock_hotkey,
        )
        self.store.save()
        save_hotkey_mirror(self.unlock_hotkey)
        QMessageBox.information(self, tr("saved_title"), tr("settings_saved"))

    def _set_hotkey(self) -> None:
        dlg = HotkeyDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.unlock_hotkey = dlg.value
            self.hotkey_value.setText(_hotkey_text(self.unlock_hotkey))

    def _clear_hotkey(self) -> None:
        self.unlock_hotkey = ""
        self.hotkey_value.setText(_hotkey_text(self.unlock_hotkey))

    def _test_camera(self) -> None:
        """用当前(未保存的)索引抓一帧弹窗预览,确认是不是想要的那台摄像头。"""
        idx = self.camera_spin.value()
        self.camera_test_btn.setEnabled(False)  # 防重入
        self._cam_test = CameraTestWorker(idx)
        self._cam_test.ok.connect(self._on_cam_test_ok)
        self._cam_test.failed.connect(lambda _e: self._on_cam_test_fail(idx))
        self._cam_test.finished.connect(lambda: self.camera_test_btn.setEnabled(True))
        self._cam_test.start()

    def _on_cam_test_ok(self, img: QImage) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("camera_test_title"))
        lbl = QLabel()
        lbl.setFixedSize(PREVIEW_W // 2, PREVIEW_H // 2)
        lbl.setAlignment(Qt.AlignCenter)
        _show_frame(lbl, img)
        lay = QVBoxLayout(dlg)
        lay.addWidget(lbl)
        dlg.exec()

    def _on_cam_test_fail(self, idx: int) -> None:
        QMessageBox.warning(self, tr("camera_test_title"), tr("camera_test_fail", idx=idx))


def _is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _relaunch_elevated() -> bool:
    import ctypes

    shell_execute = ctypes.windll.shell32.ShellExecuteW
    shell_execute.restype = ctypes.c_void_p
    result = shell_execute(
        None, "runas", sys.executable, "-m app.main", str(config.INSTALL_ROOT), 1
    )
    return int(result or 0) > 32


def _run_service(*args: str) -> tuple[int, str]:
    """调 `python winservice_main.py <args>`(install/start/stop/remove)。需管理员。"""
    import subprocess

    cmd = [sys.executable, str(config.ROOT / "winservice_main.py"), *args]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def _service_status() -> str:
    try:
        st = probes.query_service().status
        key = probes.service_state_key(st)
        return tr(key) if key else tr("svc_code", st=st)
    except Exception:  # noqa: BLE001 多半是未安装
        return tr("svc_not_installed")


class ServiceTab(QWidget):
    """服务与凭据:设 LSA 解锁密码 + 安装/启停 LocalSystem 自启服务。需管理员。"""

    def __init__(self, store: FaceStore):
        super().__init__()
        self.store = store
        self.user = cred_vault.current_user()
        self.is_admin = _is_admin()
        self.diag_worker: DiagnosticsWorker | None = None
        self.diag_report: DiagnosticReport | None = None

        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.Password)
        self.pwd_edit.setPlaceholderText(tr("unlock_pwd_placeholder"))
        save_pwd_btn = QPushButton(tr("save_unlock_pwd"))
        save_pwd_btn.setObjectName("accent")
        save_pwd_btn.clicked.connect(self._save_pwd)

        install_btn = QPushButton(tr("install_autostart"))
        install_btn.setObjectName("accent")
        install_btn.clicked.connect(self._install)
        start_btn = QPushButton(tr("btn_start"))
        start_btn.clicked.connect(lambda: self._svc_cmd("start"))
        stop_btn = QPushButton(tr("btn_stop"))
        stop_btn.clicked.connect(lambda: self._svc_cmd("stop"))
        remove_btn = QPushButton(tr("btn_uninstall"))
        remove_btn.clicked.connect(self._remove)
        refresh_btn = QPushButton(tr("btn_refresh"))
        refresh_btn.clicked.connect(self._refresh_status)
        register_btn = QPushButton(tr("register_cp"))
        register_btn.setObjectName("accent")
        register_btn.clicked.connect(lambda: self._register_cp(unregister=False))
        unregister_btn = QPushButton(tr("unregister_cp"))
        unregister_btn.clicked.connect(lambda: self._register_cp(unregister=True))
        self.svc_status = QLabel("—")
        self.svc_status.setObjectName("hint")
        self.diag_run_btn = QPushButton(tr("diag_run"))
        self.diag_run_btn.setObjectName("accent")
        self.diag_run_btn.clicked.connect(self._run_diagnostics)
        self.diag_copy_btn = QPushButton(tr("diag_copy"))
        self.diag_copy_btn.setEnabled(False)
        self.diag_copy_btn.clicked.connect(self._copy_diagnostics)
        self.diag_summary = QLabel(tr("diag_idle"))
        self.diag_summary.setObjectName("hint")
        self.diag_table = QTableWidget(0, 4)
        self.diag_table.setHorizontalHeaderLabels(
            [tr("diag_col_item"), tr("diag_col_status"), tr("diag_col_detail"), tr("diag_col_advice")]
        )
        self.diag_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.diag_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.diag_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.diag_table.setWordWrap(False)
        self.diag_table.setMinimumHeight(190)

        # 这些动作都需管理员,非管理员时禁用
        self._admin_widgets = [
            self.pwd_edit, save_pwd_btn, install_btn, start_btn, stop_btn, remove_btn,
            register_btn, unregister_btn,
        ]

        account_lbl = QLabel(tr("current_account", user=self.user))
        account_lbl.setObjectName("hint")
        step1 = QLabel(tr("step1"))
        step1.setObjectName("h2")
        step1.setWordWrap(True)
        step2 = QLabel(tr("step2"))
        step2.setObjectName("h2")
        step2.setWordWrap(True)
        step3 = QLabel(tr("step3"))
        step3.setObjectName("h2")
        step3.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)
        layout.addWidget(account_lbl)
        if not self.is_admin:
            warn = QLabel(tr("admin_warn"))
            warn.setStyleSheet(f"color:{DANGER};")
            warn.setWordWrap(True)
            layout.addWidget(warn)

        layout.addSpacing(8)
        layout.addWidget(step1)
        pwd_row = QHBoxLayout()
        pwd_row.addWidget(self.pwd_edit, 1)
        pwd_row.addWidget(save_pwd_btn)
        layout.addLayout(pwd_row)

        layout.addSpacing(12)
        layout.addWidget(step2)
        svc_row = QHBoxLayout()
        for b in (install_btn, start_btn, stop_btn, remove_btn, refresh_btn):
            svc_row.addWidget(b)
        layout.addLayout(svc_row)
        layout.addWidget(self.svc_status)

        layout.addSpacing(12)
        layout.addWidget(step3)
        cp_row = QHBoxLayout()
        cp_row.addWidget(register_btn)
        cp_row.addWidget(unregister_btn)
        cp_row.addStretch(1)
        layout.addLayout(cp_row)

        layout.addSpacing(12)
        diag_title = QLabel(tr("diag_title"))
        diag_title.setObjectName("h2")
        layout.addWidget(diag_title)
        diag_row = QHBoxLayout()
        diag_row.addWidget(self.diag_run_btn)
        diag_row.addWidget(self.diag_copy_btn)
        diag_row.addStretch(1)
        layout.addLayout(diag_row)
        layout.addWidget(self.diag_summary)
        layout.addWidget(self.diag_table, 1)

        if not self.is_admin:
            for w in self._admin_widgets:
                w.setEnabled(False)
        self._refresh_status()

    def _save_pwd(self) -> None:
        pwd = self.pwd_edit.text()
        if not pwd:
            QMessageBox.warning(self, tr("tip"), tr("enter_pwd"))
            return
        try:
            cred_vault.store_password(self.user, pwd)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("failed_title"), tr("lsa_write_fail", e=e))
            return
        self.pwd_edit.clear()
        QMessageBox.information(self, tr("done_title"), tr("pwd_saved", user=self.user))

    def _svc_cmd(self, action: str) -> None:
        rc, out = _run_service(action)
        self._refresh_status()
        if rc != 0:
            QMessageBox.warning(self, action, out or tr("ret_code", action=action, rc=rc))

    def _install(self) -> None:
        # 注意:HandleCommandLine 要求选项在命令之前(--startup auto install)
        rc, out = _run_service("--startup", "auto", "install")
        if rc == 0:
            _run_service("start")
            self._refresh_status()
            QMessageBox.information(self, tr("install_title"), tr("install_ok"))
        else:
            self._refresh_status()
            QMessageBox.warning(self, tr("install_title"), out or tr("ret_code_simple", rc=rc))

    def _remove(self) -> None:
        _run_service("stop")
        rc, out = _run_service("remove")
        self._refresh_status()
        if rc != 0:
            QMessageBox.warning(self, tr("uninstall_title"), out or tr("ret_code_simple", rc=rc))

    def _register_cp(self, unregister: bool) -> None:
        """regsvr32 注册/反注册 CP DLL(锁屏磁贴)。安装包已自动做,此处供排错/手动刷新。"""
        import subprocess

        action = tr("act_unregister") if unregister else tr("act_register")
        dll = config.CP_DLL
        if not dll.exists():
            QMessageBox.warning(self, tr("dll_not_found_title"), tr("dll_not_found", dll=dll))
            return
        args = ["regsvr32", "/s"] + (["/u"] if unregister else []) + [str(dll)]
        p = subprocess.run(args, capture_output=True, text=True)
        if p.returncode == 0:
            QMessageBox.information(self, action, tr("cp_action_done", action=action))
        else:
            msg = (p.stdout + p.stderr).strip()
            QMessageBox.warning(self, action, msg or tr("regsvr_code", rc=p.returncode))

    def _refresh_status(self) -> None:
        self.svc_status.setText(tr("svc_status_prefix") + _service_status())

    def _run_diagnostics(self) -> None:
        self.diag_run_btn.setEnabled(False)
        self.diag_copy_btn.setEnabled(False)
        self.diag_table.setRowCount(0)
        lang = self.store.get_settings().get("language", "zh")
        self.diag_worker = DiagnosticsWorker(lang)
        self.diag_worker.progress.connect(self._on_diag_progress)
        self.diag_worker.done.connect(self._on_diag_done)
        self.diag_worker.finished.connect(self._on_diag_finished)
        self.diag_worker.start()

    def _on_diag_progress(self, step: str) -> None:
        self.diag_summary.setText(tr("diag_running", step=step))

    def _on_diag_done(self, report: DiagnosticReport) -> None:
        self.diag_report = report
        lang = self.store.get_settings().get("language", "zh")
        self.diag_summary.setText(tr("diag_summary", status=status_label(report.overall_status, lang)))
        self._load_diag_table(report)

    def _on_diag_finished(self) -> None:
        self.diag_worker = None
        self.diag_run_btn.setEnabled(True)
        self.diag_copy_btn.setEnabled(self.diag_report is not None)

    def _load_diag_table(self, report: DiagnosticReport) -> None:
        lang = self.store.get_settings().get("language", "zh")
        colors = {
            "ok": SUCCESS,
            "warn": WARN,
            "fail": DANGER,
            "info": "#5A5A5A",
        }
        self.diag_table.setRowCount(len(report.items))
        for row, item in enumerate(report.items):
            cells = [item.name, status_label(item.status, lang), item.detail, item.advice]
            for col, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if col == 1:
                    cell.setForeground(QBrush(QColor(colors.get(item.status, "#5A5A5A"))))
                self.diag_table.setItem(row, col, cell)
        self.diag_table.resizeRowsToContents()

    def _copy_diagnostics(self) -> None:
        if self.diag_report is None:
            return
        lang = self.store.get_settings().get("language", "zh")
        QApplication.clipboard().setText(self.diag_report.to_text(lang))
        QMessageBox.information(self, tr("diag_title"), tr("diag_copy_ok"))


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("rootWindow")
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._drag_pos: QPoint | None = None
        self._closing = False
        self._close_ready = False
        self.detector = FaceDetector()  # 惰性加载,首次推理时才载入模型
        self.store = FaceStore().load()
        # 建任何控件前先按持久化设置定语言;切换语言改的是设置,重启控制台后整体生效
        set_lang(self.store.get_settings().get("language", "zh"))
        self.setWindowTitle(tr("app_title"))

        self.enroll_tab = EnrollTab(self.detector, self.store)
        self.auth_tab = AuthTab(self.detector, self.store)
        self.service_tab = ServiceTab(self.store)
        self.settings_tab = SettingsTab(self.store)
        self.stack = QStackedWidget()
        for page in (self.enroll_tab, self.auth_tab, self.service_tab, self.settings_tab):
            self.stack.addWidget(page)

        self.lang_combo = QComboBox()
        self.lang_combo.addItem("中文", "zh")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.setCurrentIndex(0 if self.store.get_settings().get("language", "zh") != "en" else 1)
        self.lang_combo.setToolTip("重启后生效 / Takes effect after restart")
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)  # 连在 setCurrentIndex 之后,避免启动误触
        self.status_label = QLabel(tr("model_loading"))
        self.status_label.setStyleSheet(f"color:{WARN};background:transparent;")

        self.nav_buttons: list[QPushButton] = []
        nav_col = QVBoxLayout()
        nav_col.setContentsMargins(0, 0, 0, 0)
        nav_col.setSpacing(6)
        for i, text in enumerate((tr("tab_enroll"), tr("tab_test"), tr("tab_service"), tr("tab_settings"))):
            btn = QPushButton(text)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setProperty("pageIndex", i)
            btn.clicked.connect(self._on_nav_clicked)
            self.nav_buttons.append(btn)
            nav_col.addWidget(btn)
        self.nav_buttons[0].setChecked(True)

        brand = QLabel("FaceHello")
        brand.setObjectName("brand")
        side_hint = QLabel(tr("app_title").replace("_", ""))
        side_hint.setObjectName("sideHint")
        self.status_label.setObjectName("sideHint")
        self.status_label.setWordWrap(True)

        sidebar = QWidget()
        sidebar.setObjectName("sideBar")
        sidebar.setFixedWidth(210)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(16, 16, 16, 16)
        side_layout.setSpacing(12)
        side_layout.addWidget(brand)
        side_layout.addWidget(side_hint)
        side_layout.addSpacing(10)
        side_layout.addLayout(nav_col)
        side_layout.addStretch(1)
        lang_label = QLabel("Language")
        lang_label.setObjectName("sideHint")
        self.lang_combo.setObjectName("sideCombo")
        side_layout.addWidget(lang_label)
        side_layout.addWidget(self.lang_combo)
        side_layout.addWidget(self.status_label)

        content = QWidget()
        content.setObjectName("contentPanel")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self.stack)

        self.title_bar = QWidget()
        self.title_bar.setObjectName("titleBar")
        self.title_bar.setFixedHeight(32)
        self.title_bar.installEventFilter(self)
        min_btn = CaptionButton("min")
        max_btn = CaptionButton("max")
        close_btn = CaptionButton("close")
        self.max_btn = max_btn
        min_btn.clicked.connect(self.showMinimized)
        max_btn.clicked.connect(self._toggle_max_restore)
        close_btn.clicked.connect(self.close)

        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(4)
        title_layout.addStretch(1)
        title_layout.addWidget(min_btn)
        title_layout.addWidget(max_btn)
        title_layout.addWidget(close_btn)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)
        body.addWidget(sidebar)
        body.addWidget(content, 1)

        shell = QWidget()
        shell.setObjectName("windowShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(18, 10, 18, 10)
        shell_layout.setSpacing(8)
        shell_layout.addWidget(self.title_bar)
        shell_layout.addLayout(body, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(shell)

        self._resize_handles = [
            ResizeHandle(self, Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.CursorShape.SizeFDiagCursor),
            ResizeHandle(self, Qt.Edge.TopEdge, Qt.CursorShape.SizeVerCursor),
            ResizeHandle(self, Qt.Edge.TopEdge | Qt.Edge.RightEdge, Qt.CursorShape.SizeBDiagCursor),
            ResizeHandle(self, Qt.Edge.RightEdge, Qt.CursorShape.SizeHorCursor),
            ResizeHandle(self, Qt.Edge.BottomEdge | Qt.Edge.RightEdge, Qt.CursorShape.SizeFDiagCursor),
            ResizeHandle(self, Qt.Edge.BottomEdge, Qt.CursorShape.SizeVerCursor),
            ResizeHandle(self, Qt.Edge.BottomEdge | Qt.Edge.LeftEdge, Qt.CursorShape.SizeBDiagCursor),
            ResizeHandle(self, Qt.Edge.LeftEdge, Qt.CursorShape.SizeHorCursor),
        ]
        self._layout_resize_handles()

        # 启动即后台预加载识别模型,把加载耗时挪出录入/解锁路径
        self._warmup = WarmupWorker(self.detector)
        self._warmup.ready.connect(self._on_ready)
        self._warmup.start()

        self._warn_renewal_due()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.title_bar:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if event.type() == QEvent.MouseMove and self._drag_pos is not None:
                if event.buttons() & Qt.LeftButton:
                    if self.isMaximized():
                        self.showNormal()
                    self.move(event.globalPosition().toPoint() - self._drag_pos)
                    return True
            if event.type() == QEvent.MouseButtonRelease:
                self._drag_pos = None
                return True
            if event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                self._toggle_max_restore()
                return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_resize_handles()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            self._layout_resize_handles()

    def _layout_resize_handles(self) -> None:
        if not hasattr(self, "_resize_handles"):
            return
        w, h = self.width(), self.height()
        border = 8
        corner = 16
        geometries = [
            (0, 0, corner, corner),
            (corner, 0, max(0, w - corner * 2), border),
            (w - corner, 0, corner, corner),
            (w - border, corner, border, max(0, h - corner * 2)),
            (w - corner, h - corner, corner, corner),
            (corner, h - border, max(0, w - corner * 2), border),
            (0, h - corner, corner, corner),
            (0, corner, border, max(0, h - corner * 2)),
        ]
        visible = not self.isMaximized()
        for handle, geometry in zip(self._resize_handles, geometries):
            handle.setGeometry(*geometry)
            handle.setVisible(visible)
            if visible:
                handle.raise_()

    def _toggle_max_restore(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self.max_btn.set_kind("max")
        else:
            self.showMaximized()
            self.max_btn.set_kind("restore")

    def _on_nav_clicked(self) -> None:
        btn = self.sender()
        if not isinstance(btn, QPushButton):
            return
        index = int(btn.property("pageIndex"))
        self.stack.setCurrentIndex(index)
        for nav in self.nav_buttons:
            nav.setChecked(nav is btn)

    def _on_lang_changed(self) -> None:
        lang = self.lang_combo.currentData()
        self.store.update_settings(language=lang)
        self.store.save()
        save_lang_mirror(lang)  # 锁屏磁贴(C++ CP)据此切换;尽力而为
        # 双语提示:切换后当前进程仍是旧语言,故消息固定双语,两种用户都读得懂
        QMessageBox.information(
            self, "Language / 语言",
            "已切换,重启控制台后整体生效。\nSwitched. Restart the console to apply.",
        )

    def _on_ready(self) -> None:
        self.status_label.setText(tr("model_ready"))
        self.status_label.setStyleSheet(f"color:{SUCCESS};background:transparent;")

    def _warn_renewal_due(self) -> None:
        due = list(dict.fromkeys(
            p.name for p in self.store.list_profiles() if p.renewal_due
        ))
        if due:
            QMessageBox.warning(
                self, tr("renewal_due_title"),
                tr("renewal_due_body") + tr("list_sep").join(due),
            )

    def closeEvent(self, event) -> None:
        if self._close_ready:
            super().closeEvent(event)
            return
        workers = self._active_workers()
        if not workers:
            super().closeEvent(event)
            return
        if not self._closing:
            self._closing = True
            self.setEnabled(False)
            for worker in workers:
                stop = getattr(worker, "stop", None)
                if stop is not None:
                    stop()
            QTimer.singleShot(100, self._finish_close)
        event.ignore()

    def _active_workers(self) -> list:
        workers = [
            self.enroll_tab.worker,
            self.auth_tab.worker,
            self.auth_tab.monitor,
            self.settings_tab._cam_test,
            self.settings_tab._update_check,
            self.settings_tab._update_download,
            self.service_tab.diag_worker,
            self._warmup,
        ]
        return [worker for worker in workers if worker is not None and worker.isRunning()]

    def _finish_close(self) -> None:
        if self._active_workers():
            QTimer.singleShot(100, self._finish_close)
            return
        self._close_ready = True
        self.close()


# 自定义应用图标:放 app/assets/facehello.ico(随 app/ 一起被安装器打包)。
# 缺文件则回退默认图标,不报错。
_ICON_PATH = Path(__file__).resolve().parent / "assets" / "facehello.ico"


def _app_icon() -> QIcon:
    """加载多尺寸 .ico。QIcon 读路径会带上全部尺寸(任务栏/高分屏才清晰);
    用 loadFromData 只会取首帧(16px)被放大糊掉。Qt 对 Unicode(中文)路径安全。
    缺文件返回空 QIcon(回退默认图标)。"""
    if not _ICON_PATH.exists():
        return QIcon()
    return QIcon(str(_ICON_PATH))


def _set_app_user_model_id() -> None:
    """让 Windows 任务栏按本应用分组并显示自定义图标,而非默认 python 图标。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FaceHello.Console")
    except Exception:  # noqa: BLE001 失败不致命
        pass


def _acquire_console_mutex() -> bool:
    global _CONSOLE_MUTEX
    if sys.platform != "win32":
        return True
    import ctypes

    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\FaceHello.Console")
    if not handle:
        return False
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.kernel32.CloseHandle(handle)
        return False
    _CONSOLE_MUTEX = handle
    return True


def main() -> None:
    _set_app_user_model_id()
    app = QApplication(sys.argv)
    app.setWindowIcon(_app_icon())  # 窗口 + 任务栏 + 所有对话框的默认图标
    app.setStyleSheet(_themed_qss())
    if config.IS_INSTALLED and not _is_admin():
        if not _relaunch_elevated():
            QMessageBox.warning(None, tr("failed_title"), tr("admin_console_required"))
        return
    if not _acquire_console_mutex():
        return
    win = MainWindow()
    win.setMinimumSize(1040, 640)
    win.resize(1180, 720)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
