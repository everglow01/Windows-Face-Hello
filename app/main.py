"""Face_hello 管理台入口。

运行:  uv run python -m app.main
三个标签页:录入人脸 / 测试解锁 / 设置与安全。
注意:这是管理/验证用的桌面程序,真正在锁屏解锁需后续的 Credential Provider(阶段 5)。
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
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
from face_hello.auth import AuthResult
from face_hello.detector import FaceDetector
from face_hello.store import FaceStore

PREVIEW_W, PREVIEW_H = 640, 480


def _preview_label() -> QLabel:
    lbl = QLabel("摄像头预览")
    lbl.setFixedSize(PREVIEW_W, PREVIEW_H)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setStyleSheet("background:#222;color:#aaa;border:1px solid #444;")
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
        self.name_edit.setPlaceholderText("用户名(如 owen)")
        self.start_btn = QPushButton("开始录入")
        self.start_btn.clicked.connect(self._start)
        self.preview = _preview_label()
        self.status = QLabel("输入用户名后开始;请正对摄像头,光线充足。")

        top = QHBoxLayout()
        top.addWidget(QLabel("用户名:"))
        top.addWidget(self.name_edit, 1)
        top.addWidget(self.start_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.preview, alignment=Qt.AlignCenter)
        layout.addWidget(self.status)

    def _start(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入用户名")
            return
        samples = self.store.get_settings()["enroll_samples"]
        self.start_btn.setEnabled(False)
        self.status.setText("正在打开摄像头…")
        self.worker = EnrollWorker(self.detector, samples)
        self.worker.preview.connect(lambda img: _show_frame(self.preview, img))
        self.worker.status.connect(self.status.setText)
        self.worker.progress.connect(
            lambda c, t: self.status.setText(f"拍摄中 {c}/{t} …")
        )
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_fail)
        self.worker.start()

    def _on_done(self, embedding) -> None:
        name = self.name_edit.text().strip()
        self.store.add_profile(name, embedding)
        self.store.save()
        self.status.setText(f"✅ 已录入「{name}」")
        self.start_btn.setEnabled(True)
        self.on_changed()
        QMessageBox.information(self, "完成", f"用户「{name}」录入成功")

    def _on_fail(self, msg: str) -> None:
        self.status.setText(f"❌ 失败:{msg}")
        self.start_btn.setEnabled(True)


class AuthTab(QWidget):
    def __init__(self, detector: FaceDetector, store: FaceStore):
        super().__init__()
        self.detector = detector
        self.store = store
        self.worker: AuthWorker | None = None

        self.start_btn = QPushButton("开始测试解锁")
        self.start_btn.clicked.connect(self._start)
        self.preview = _preview_label()
        self.instruction = QLabel("点击开始,按提示完成活体动作")
        self.instruction.setAlignment(Qt.AlignCenter)
        self.instruction.setStyleSheet("font-size:20px;font-weight:bold;padding:8px;")

        layout = QVBoxLayout(self)
        layout.addWidget(self.start_btn)
        layout.addWidget(self.preview, alignment=Qt.AlignCenter)
        layout.addWidget(self.instruction)

    def _start(self) -> None:
        if self.store.is_empty():
            QMessageBox.warning(self, "提示", "尚未录入任何人脸,请先在「录入」页登记")
            return
        self.start_btn.setEnabled(False)
        self.instruction.setStyleSheet("font-size:20px;font-weight:bold;padding:8px;")
        self.instruction.setText("准备中…")
        self.worker = AuthWorker(self.detector, self.store)
        self.worker.preview.connect(lambda img: _show_frame(self.preview, img))
        self.worker.instruction.connect(self.instruction.setText)
        self.worker.finished_result.connect(self._on_result)
        self.worker.failed.connect(self._on_fail)
        self.worker.start()

    def _on_result(self, result: AuthResult) -> None:
        self.start_btn.setEnabled(True)
        if result.success:
            self.instruction.setStyleSheet(
                "font-size:20px;font-weight:bold;padding:8px;color:#2e7d32;"
            )
            self.instruction.setText(f"✅ 解锁通过 — {result.name}(相似度 {result.similarity:.3f})")
        else:
            self.instruction.setStyleSheet(
                "font-size:20px;font-weight:bold;padding:8px;color:#c62828;"
            )
            self.instruction.setText(f"❌ 拒绝 — {result.reason}")

    def _on_fail(self, msg: str) -> None:
        self.start_btn.setEnabled(True)
        self.instruction.setText(f"❌ 错误:{msg}")


class SettingsTab(QWidget):
    def __init__(self, store: FaceStore):
        super().__init__()
        self.store = store

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["用户名", "录入日期", "剩余天数", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.del_btn = QPushButton("删除选中用户")
        self.del_btn.clicked.connect(self._delete_selected)

        s = self.store.get_settings()
        self.match_spin = self._dspin(0.0, 1.0, 0.01, s["match_threshold"])
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

        save_btn = QPushButton("保存设置")
        save_btn.clicked.connect(self._save)

        form = QVBoxLayout()
        form.addLayout(self._row("匹配阈值(越高越严):", self.match_spin))
        form.addLayout(self._row("转头判定角度(°):", self.yaw_spin))
        form.addLayout(self._row("眨眼挑战次数:", self.blink_spin))
        form.addLayout(self._row("人脸有效期(天):", self.renew_spin))
        form.addLayout(self._row("录入采集帧数:", self.samples_spin))

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("已录入用户"))
        layout.addWidget(self.table)
        layout.addWidget(self.del_btn)
        layout.addSpacing(12)
        layout.addWidget(QLabel("参数与安全策略"))
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
            status = "⚠ 已过期" if p.is_expired else "正常"
            cells = [p.name, p.enroll_date.isoformat(), str(p.days_left), status]
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(text))

    def _delete_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        name = self.table.item(row, 0).text()
        if QMessageBox.question(self, "确认", f"删除用户「{name}」?") == QMessageBox.Yes:
            self.store.remove_profile(name)
            self.store.save()
            self.refresh()

    def _save(self) -> None:
        self.store.update_settings(
            match_threshold=self.match_spin.value(),
            yaw_threshold_deg=self.yaw_spin.value(),
            required_blinks=self.blink_spin.value(),
            renew_days=self.renew_spin.value(),
            enroll_samples=self.samples_spin.value(),
        )
        self.store.save()
        QMessageBox.information(self, "已保存", "设置已保存")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Face_hello 管理台")
        self.detector = FaceDetector()  # 惰性加载,首次推理时才载入模型
        self.store = FaceStore().load()

        tabs = QTabWidget()
        self.settings_tab = SettingsTab(self.store)
        self.enroll_tab = EnrollTab(self.detector, self.store, self.settings_tab.refresh)
        self.auth_tab = AuthTab(self.detector, self.store)
        tabs.addTab(self.enroll_tab, "录入人脸")
        tabs.addTab(self.auth_tab, "测试解锁")
        tabs.addTab(self.settings_tab, "设置与安全")

        self.status_label = QLabel("● 模型加载中…")
        self.status_label.setStyleSheet("color:#b26a00;padding:2px 4px;")

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(self.status_label)

        # 启动即后台预加载识别模型,把加载耗时挪出录入/解锁路径
        self._warmup = WarmupWorker(self.detector)
        self._warmup.ready.connect(self._on_ready)
        self._warmup.start()

        self._warn_expired()

    def _on_ready(self) -> None:
        self.status_label.setText("● 就绪")
        self.status_label.setStyleSheet("color:#2e7d32;padding:2px 4px;")

    def _warn_expired(self) -> None:
        expired = [p.name for p in self.store.list_profiles() if p.is_expired]
        if expired:
            QMessageBox.warning(
                self, "人脸已过期",
                "以下用户人脸已超过有效期,建议重新录入:\n" + "、".join(expired),
            )


def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(720, 760)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
