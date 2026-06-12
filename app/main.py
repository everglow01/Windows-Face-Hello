"""Face_hello 管理台入口。

运行:  uv run python -m app.main
三个标签页:录入人脸 / 测试解锁 / 设置与安全。
注意:这是管理/验证用的桌面程序,真正在锁屏解锁需后续的 Credential Provider(阶段 5)。
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.workers import AuthWorker, EnrollWorker, WarmupWorker
from face_hello import config, cred_vault
from face_hello.auth import AuthResult
from face_hello.detector import FaceDetector
from face_hello.i18n import save_lang_mirror, set_lang, tr
from face_hello.store import FaceStore

PREVIEW_W, PREVIEW_H = 640, 480

# Fluent 语义色(供内联状态样式用;QSS 里另直接写色值)
ACCENT = "#0067C0"
SUCCESS = "#0F7B0F"
DANGER = "#C42B1C"
WARN = "#9D5D00"

# 大号活体提示文字的基础样式(颜色随结果在内联追加)
_INSTR_BASE = "font-size:18px;font-weight:600;padding:8px;"

# Win11 Fluent 浅色主题
FLUENT_QSS = """
* {
    font-family: "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI",
                 "Microsoft YaHei", sans-serif;
    font-size: 14px;
    color: #1A1A1A;
}
QWidget { background-color: #F3F3F3; }

QTabWidget::pane {
    border: 1px solid #E5E5E5;
    border-radius: 8px;
    background: #FFFFFF;
}
QTabBar::tab {
    background: transparent;
    color: #5A5A5A;
    padding: 8px 18px;
    margin: 2px;
    border-radius: 6px;
}
QTabBar::tab:hover { background: #EAEAEA; }
QTabBar::tab:selected {
    background: #FFFFFF;
    color: #0067C0;
    font-weight: 600;
}

QPushButton {
    background-color: #FFFFFF;
    border: 1px solid #D1D1D1;
    border-radius: 6px;
    padding: 7px 16px;
}
QPushButton:hover { background-color: #F9F9F9; border-color: #C4C4C4; }
QPushButton:pressed { background-color: #EFEFEF; }
QPushButton:disabled { background-color: #F5F5F5; color: #A0A0A0; border-color: #E8E8E8; }

QPushButton#accent {
    background-color: #0067C0;
    border: 1px solid #0067C0;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton#accent:hover { background-color: #1976C8; border-color: #1976C8; }
QPushButton#accent:pressed { background-color: #005BA1; border-color: #005BA1; }
QPushButton#accent:disabled { background-color: #B9D4EC; border-color: #B9D4EC; color: #EAF2FB; }

QLineEdit, QSpinBox, QDoubleSpinBox {
    background: #FFFFFF;
    border: 1px solid #D1D1D1;
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: #0067C0;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #0067C0; }

/* 自定义边框后必须显式给上下按钮几何,否则点击区域塌陷、点上三角会落到输入框上 */
QSpinBox, QDoubleSpinBox { padding-right: 22px; }
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid #D1D1D1;
    border-top-right-radius: 6px;
    background: #F7F7F7;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 20px;
    border-left: 1px solid #D1D1D1;
    border-bottom-right-radius: 6px;
    background: #F7F7F7;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: #E8E8E8; }
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed { background: #DDDDDD; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(__UP_ARROW__); }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(__DOWN_ARROW__); }

QTableWidget {
    background: #FFFFFF;
    border: 1px solid #E5E5E5;
    border-radius: 8px;
    gridline-color: #F0F0F0;
}
QTableWidget::item { padding: 6px; }
QTableWidget::item:selected { background: #E5F1FB; color: #1A1A1A; }
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


def _themed_qss() -> str:
    """生成箭头图标到临时目录(纯 ASCII 路径),把其路径填进 QSS。"""
    import os
    import tempfile

    tmp = tempfile.gettempdir()
    up = os.path.join(tmp, "facehello_spin_up.png").replace("\\", "/")
    down = os.path.join(tmp, "facehello_spin_down.png").replace("\\", "/")
    _make_arrow(up, True)
    _make_arrow(down, False)
    return FLUENT_QSS.replace("__UP_ARROW__", up).replace("__DOWN_ARROW__", down)


def _preview_label() -> QLabel:
    lbl = QLabel(tr("camera_preview"))
    lbl.setFixedSize(PREVIEW_W, PREVIEW_H)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setStyleSheet(
        "background:#2B2B2B;color:#C8C8C8;border:1px solid #E5E5E5;border-radius:8px;"
    )
    return lbl


def _show_frame(label: QLabel, img: QImage) -> None:
    label.setPixmap(
        QPixmap.fromImage(img).scaled(
            label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
    )


class EnrollTab(QWidget):
    def __init__(self, detector: FaceDetector, store: FaceStore, on_changed):
        super().__init__()
        self.detector = detector
        self.store = store
        self.on_changed = on_changed
        self.worker: EnrollWorker | None = None

        self.name_edit = QLineEdit()
        # 预填当前 Windows 账户名:档案名必须等于该账户名,锁屏刷脸才能对上 LSA 密码 + KERB
        self.name_edit.setText(cred_vault.current_user())
        self.name_edit.setPlaceholderText(tr("win_account_name"))
        self.start_btn = QPushButton(tr("start_enroll"))
        self.start_btn.setObjectName("accent")
        self.start_btn.clicked.connect(self._start)
        self.preview = _preview_label()
        self.status = QLabel(tr("enroll_hint"))
        self.status.setObjectName("hint")

        top = QHBoxLayout()
        top.addWidget(QLabel(tr("username_label")))
        top.addWidget(self.name_edit, 1)
        top.addWidget(self.start_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addLayout(top)
        layout.addWidget(self.preview, alignment=Qt.AlignCenter)
        layout.addWidget(self.status)

    def _start(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, tr("tip"), tr("enter_username"))
            return
        samples = self.store.get_settings()["enroll_samples"]
        self.start_btn.setEnabled(False)
        self.status.setText(tr("opening_camera"))
        self.worker = EnrollWorker(self.detector, samples)
        self.worker.preview.connect(lambda img: _show_frame(self.preview, img))
        self.worker.status.connect(self.status.setText)
        self.worker.progress.connect(
            lambda c, n: self.status.setText(tr("capturing", cur=c, tot=n))
        )
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_fail)
        self.worker.start()

    def _on_done(self, embedding) -> None:
        name = self.name_edit.text().strip()
        self.store.add_profile(name, embedding)
        self.store.save()
        self.status.setText(tr("enrolled_ok", name=name))
        self.start_btn.setEnabled(True)
        self.on_changed()
        QMessageBox.information(self, tr("done_title"), tr("enroll_success", name=name))

    def _on_fail(self, msg: str) -> None:
        self.status.setText(tr("failed_fmt", msg=msg))
        self.start_btn.setEnabled(True)


class AuthTab(QWidget):
    def __init__(self, detector: FaceDetector, store: FaceStore):
        super().__init__()
        self.detector = detector
        self.store = store
        self.worker: AuthWorker | None = None

        self.start_btn = QPushButton(tr("start_test_unlock"))
        self.start_btn.setObjectName("accent")
        self.start_btn.clicked.connect(self._start)
        self.preview = _preview_label()
        self.instruction = QLabel(tr("auth_idle_hint"))
        self.instruction.setAlignment(Qt.AlignCenter)
        self.instruction.setStyleSheet(_INSTR_BASE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(self.start_btn)
        layout.addWidget(self.preview, alignment=Qt.AlignCenter)
        layout.addWidget(self.instruction)

    def _start(self) -> None:
        if self.store.is_empty():
            QMessageBox.warning(self, tr("tip"), tr("no_enroll_warn"))
            return
        self.start_btn.setEnabled(False)
        self.instruction.setStyleSheet(_INSTR_BASE)
        self.instruction.setText(tr("preparing"))
        self.worker = AuthWorker(self.detector, self.store)
        self.worker.preview.connect(lambda img: _show_frame(self.preview, img))
        self.worker.instruction.connect(self.instruction.setText)
        self.worker.finished_result.connect(self._on_result)
        self.worker.failed.connect(self._on_fail)
        self.worker.start()

    def _on_result(self, result: AuthResult) -> None:
        self.start_btn.setEnabled(True)
        if result.success:
            self.instruction.setStyleSheet(_INSTR_BASE + f"color:{SUCCESS};")
            self.instruction.setText(tr("unlock_pass", name=result.name, sim=result.similarity))
        else:
            self.instruction.setStyleSheet(_INSTR_BASE + f"color:{DANGER};")
            self.instruction.setText(tr("unlock_reject", reason=result.reason))

    def _on_fail(self, msg: str) -> None:
        self.start_btn.setEnabled(True)
        self.instruction.setText(tr("error_fmt", msg=msg))


class SettingsTab(QWidget):
    def __init__(self, store: FaceStore):
        super().__init__()
        self.store = store

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [tr("col_user"), tr("col_enroll_date"), tr("col_days_left"), tr("col_status")]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.del_btn = QPushButton(tr("delete_selected"))
        self.del_btn.clicked.connect(self._delete_selected)

        s = self.store.get_settings()
        # 界面语言下拉:userData 存语言码,显示名固定中英两种(与当前界面语言无关)
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("中文", "zh")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.setCurrentIndex(0 if s.get("language", "zh") != "en" else 1)
        self.match_spin = self._dspin(0.0, 1.0, 0.01, s["match_threshold"])
        self.margin_spin = self._dspin(0.0, 0.5, 0.01, s.get("match_margin", 0.05))
        self.yaw_spin = self._dspin(5.0, 45.0, 1.0, s["yaw_threshold_deg"])
        self.blink_spin = QSpinBox()
        self.blink_spin.setRange(1, 5)
        self.blink_spin.setValue(s["required_blinks"])
        self.renew_spin = QSpinBox()
        self.renew_spin.setRange(1, 3650)
        self.renew_spin.setValue(s["renew_days"])
        self.samples_spin = QSpinBox()
        self.samples_spin.setRange(3, 30)
        self.samples_spin.setValue(s["enroll_samples"])
        self.liveness_check = QCheckBox(tr("liveness_check"))
        self.liveness_check.setChecked(s["liveness_enabled"])

        save_btn = QPushButton(tr("save_settings"))
        save_btn.setObjectName("accent")
        save_btn.clicked.connect(self._save)

        form = QVBoxLayout()
        form.addLayout(self._row(tr("language_label"), self.lang_combo))
        form.addWidget(self.liveness_check)
        form.addLayout(self._row(tr("match_threshold_label"), self.match_spin))
        form.addLayout(self._row(tr("match_margin_label"), self.margin_spin))
        form.addLayout(self._row(tr("yaw_label"), self.yaw_spin))
        form.addLayout(self._row(tr("blink_count_label"), self.blink_spin))
        form.addLayout(self._row(tr("renew_label"), self.renew_spin))
        form.addLayout(self._row(tr("samples_label"), self.samples_spin))

        users_title = QLabel(tr("enrolled_users"))
        users_title.setObjectName("h2")
        params_title = QLabel(tr("params_security"))
        params_title.setObjectName("h2")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(users_title)
        layout.addWidget(self.table)
        layout.addWidget(self.del_btn)
        layout.addSpacing(12)
        layout.addWidget(params_title)
        layout.addLayout(form)
        layout.addWidget(save_btn)

        self.refresh()

    @staticmethod
    def _dspin(lo, hi, step, val) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setValue(val)
        return sp

    @staticmethod
    def _row(label, widget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        row.addStretch(1)
        row.addWidget(widget)
        return row

    def refresh(self) -> None:
        profiles = self.store.list_profiles()
        self.table.setRowCount(len(profiles))
        for r, p in enumerate(profiles):
            status = tr("expired_mark") if p.is_expired else tr("normal_status")
            cells = [p.name, p.enroll_date.isoformat(), str(p.days_left), status]
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

    def _save(self) -> None:
        lang = self.lang_combo.currentData()
        self.store.update_settings(
            language=lang,
            liveness_enabled=self.liveness_check.isChecked(),
            match_threshold=self.match_spin.value(),
            match_margin=self.margin_spin.value(),
            yaw_threshold_deg=self.yaw_spin.value(),
            required_blinks=self.blink_spin.value(),
            renew_days=self.renew_spin.value(),
            enroll_samples=self.samples_spin.value(),
        )
        self.store.save()
        # 写明文镜像,锁屏磁贴(C++ CP,SYSTEM)据此切换语言;尽力而为,失败不阻断保存
        save_lang_mirror(lang)
        QMessageBox.information(self, tr("saved_title"), tr("settings_saved"))


def _is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _run_service(*args: str) -> tuple[int, str]:
    """调 `python winservice_main.py <args>`(install/start/stop/remove)。需管理员。"""
    import subprocess

    cmd = [sys.executable, str(config.ROOT / "winservice_main.py"), *args]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


# 服务状态码 → 文案 key(在 tr 之前于模块加载期求值会绑死语言,故只存 key,调用时再 tr)
_SVC_STATE_KEYS = {1: "svc_stopped", 2: "svc_starting", 3: "svc_stopping", 4: "svc_running", 7: "svc_paused"}


def _service_status() -> str:
    try:
        import win32serviceutil

        st = win32serviceutil.QueryServiceStatus(ServiceTab.SERVICE_NAME)[1]
        key = _SVC_STATE_KEYS.get(st)
        return tr(key) if key else tr("svc_code", st=st)
    except Exception:  # noqa: BLE001 多半是未安装
        return tr("svc_not_installed")


class ServiceTab(QWidget):
    """服务与凭据:设 LSA 解锁密码 + 安装/启停 LocalSystem 自启服务。需管理员。"""

    SERVICE_NAME = "FaceHello"

    def __init__(self):
        super().__init__()
        self.user = cred_vault.current_user()
        self.is_admin = _is_admin()

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
        layout.addStretch(1)

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


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.detector = FaceDetector()  # 惰性加载,首次推理时才载入模型
        self.store = FaceStore().load()
        # 建任何控件前先按持久化设置定语言;切换语言改的是设置,重启控制台后整体生效
        set_lang(self.store.get_settings().get("language", "zh"))
        self.setWindowTitle(tr("app_title"))

        tabs = QTabWidget()
        self.settings_tab = SettingsTab(self.store)
        self.enroll_tab = EnrollTab(self.detector, self.store, self.settings_tab.refresh)
        self.auth_tab = AuthTab(self.detector, self.store)
        self.service_tab = ServiceTab()
        tabs.addTab(self.enroll_tab, tr("tab_enroll"))
        tabs.addTab(self.auth_tab, tr("tab_test"))
        tabs.addTab(self.service_tab, tr("tab_service"))
        tabs.addTab(self.settings_tab, tr("tab_settings"))

        self.status_label = QLabel(tr("model_loading"))
        self.status_label.setStyleSheet(f"color:{WARN};padding:2px 4px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 10)
        layout.setSpacing(8)
        layout.addWidget(tabs)
        layout.addWidget(self.status_label)

        # 启动即后台预加载识别模型,把加载耗时挪出录入/解锁路径
        self._warmup = WarmupWorker(self.detector)
        self._warmup.ready.connect(self._on_ready)
        self._warmup.start()

        self._warn_expired()

    def _on_ready(self) -> None:
        self.status_label.setText(tr("model_ready"))
        self.status_label.setStyleSheet(f"color:{SUCCESS};padding:2px 4px;")

    def _warn_expired(self) -> None:
        expired = [p.name for p in self.store.list_profiles() if p.is_expired]
        if expired:
            QMessageBox.warning(
                self, tr("expired_title"),
                tr("expired_body") + tr("list_sep").join(expired),
            )


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(_themed_qss())
    win = MainWindow()
    win.resize(720, 760)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
