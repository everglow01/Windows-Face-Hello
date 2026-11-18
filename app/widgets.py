from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QStackedWidget, QVBoxLayout, QWidget,
)

from face_hello.i18n import tr
from app.theme import (
    BORDER,
    BORDER_CONTROL,
    DANGER,
    ON_ACCENT,
    PREVIEW,
    PREVIEW_TEXT,
    RADIUS_CARD,
    SUCCESS,
    SURFACE,
    TEXT_MUTED,
    TEXT_SECONDARY,
)

PREVIEW_W, PREVIEW_H = 560, 420


def page_label(key: str, role: str = "hint") -> QLabel:
    label = QLabel(tr(key))
    label.setObjectName(role)
    label.setWordWrap(True)
    return label


def divider() -> QFrame:
    rule = QFrame()
    rule.setObjectName("pageDivider")
    rule.setFixedHeight(1)
    return rule


def console_icon(name: str, color: str = TEXT_SECONDARY, size: int = 20) -> QIcon:
    """Small line icons shared by the sidebar and the enrollment controls."""
    pix = QPixmap(size * 3, size * 3)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(pix.width() / 24, pix.height() / 24)
    p.setPen(QPen(QColor(color), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    def stroke(*points):
        path = QPainterPath(QPointF(*points[0]))
        for point in points[1:]:
            path.lineTo(QPointF(*point))
        p.drawPath(path)

    if name == "face":
        for x, y, dx, dy in ((3, 3, 1, 1), (21, 3, -1, 1),
                             (3, 21, 1, -1), (21, 21, -1, -1)):
            stroke((x, y + 5 * dy), (x, y), (x + 5 * dx, y))
        stroke((8, 9), (8, 10))
        stroke((16, 9), (16, 10))
        path = QPainterPath(QPointF(8, 14))
        path.cubicTo(10, 17, 14, 17, 16, 14)
        p.drawPath(path)
    elif name == "camera":
        p.drawRoundedRect(QRectF(2.5, 6.5, 19, 13.5), 3, 3)
        stroke((7, 6.5), (9, 4), (15, 4), (17, 6.5))
        p.drawEllipse(QRectF(8.5, 9.5, 7, 7))
    elif name == "test":
        p.drawEllipse(QRectF(3, 3, 18, 18))
        stroke((10, 8), (16, 12), (10, 16), (10, 8))
    elif name == "service":
        p.drawRoundedRect(QRectF(2.5, 4, 19, 16), 3, 3)
        stroke((5, 12), (8, 12), (10, 8), (13, 16), (15, 12), (19, 12))
    elif name == "settings":
        for y, x in ((6, 8), (12, 16), (18, 10)):
            stroke((3, y), (x - 2, y))
            stroke((x + 2, y), (21, y))
            p.drawEllipse(QRectF(x - 2, y - 2, 4, 4))
    p.end()
    pix.setDevicePixelRatio(3)
    return QIcon(pix)


class ModeSelector(QWidget):
    """Mutually exclusive buttons backed by stable settings values."""
    changed = Signal(str)

    def __init__(self, choices, selected):
        super().__init__()
        self.buttons = {}
        group = QButtonGroup(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        for value, key in choices:
            button = QPushButton(tr(key))
            button.setObjectName("modeChoice")
            button.setCheckable(True)
            button.setProperty("mode", value)
            group.addButton(button)
            self.buttons[value] = button
            layout.addWidget(button)
        layout.addStretch()
        self.group = group
        self.set_value(selected)
        group.buttonToggled.connect(self._on_toggled)

    def _on_toggled(self, button, checked):
        if checked:
            self.changed.emit(button.property("mode"))

    def value(self):
        return self.group.checkedButton().property("mode")

    def set_value(self, value):
        self.buttons.get(value, next(iter(self.buttons.values()))).setChecked(True)


class _Viewfinder(QFrame):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#bdae9b"), 1.2))
        bounds = self.rect().adjusted(self.width() // 6, 61, -self.width() // 6, -41)
        for point, dx, dy in ((bounds.topLeft(), 1, 1), (bounds.topRight(), -1, 1),
                              (bounds.bottomLeft(), 1, -1), (bounds.bottomRight(), -1, -1)):
            corner = QPointF(point)
            painter.drawLine(corner, corner + QPointF(dx * 16, 0))
            painter.drawLine(corner, corner + QPointF(0, dy * 16))
        painter.end()


class EnrollmentPreview(QStackedWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(322)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        idle = _Viewfinder()
        idle.setObjectName("cameraIdle")
        layout = QVBoxLayout(idle)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.addWidget(page_label("camera_preview", "cameraCaption"))
        layout.addStretch()
        mark = QLabel()
        mark.setPixmap(console_icon("face", "#9c8b76", 48).pixmap(48, 48))
        layout.addWidget(mark, 0, Qt.AlignCenter)
        for key, role in (("camera_off", "previewTitle"), ("camera_idle_help", "hint")):
            label = page_label(key, role)
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label)
        layout.addStretch()
        self.addWidget(idle)
        self.live = QLabel()
        self.live.setObjectName("cameraLive")
        self.live.setAlignment(Qt.AlignCenter)
        self.live.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.addWidget(self.live)

    def set_running(self, running: bool) -> None:
        self.live.clear()
        self.setCurrentWidget(self.live if running else self.widget(0))

    def show_frame(self, image: QImage) -> None:
        show_frame(self.live, image)


class PreviewLabel(QLabel):
    def __init__(self):
        super().__init__(tr("camera_preview"))
        self.setMinimumSize(400, 300)
        self.setMaximumSize(760, 570)
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"background:{PREVIEW};color:{PREVIEW_TEXT};"
            f"border:1px solid {BORDER};border-radius:{RADIUS_CARD}px;"
        )

    def sizeHint(self) -> QSize:
        return QSize(PREVIEW_W, PREVIEW_H)

    def minimumSizeHint(self) -> QSize:
        return QSize(400, 300)

    def heightForWidth(self, width: int) -> int:
        return width * 3 // 4

    def resizeEvent(self, event) -> None:
        height = max(300, min(570, event.size().width() * 3 // 4))
        if self.maximumHeight() != height:
            self.setMaximumHeight(height)
        super().resizeEvent(event)


def preview_label() -> QLabel:
    return PreviewLabel()


def show_frame(label: QLabel, img: QImage) -> None:
    label.setPixmap(
        QPixmap.fromImage(img).scaled(
            label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
    )


class SimilarityHistogram(QWidget):
    _BINS = 20
    _WINDOW = 150

    def __init__(self):
        super().__init__()
        self._samples: deque[float] = deque(maxlen=self._WINDOW)
        self._threshold = 0.5
        self._current: float | None = None
        self.setFixedHeight(118)

    def set_threshold(self, thr: float) -> None:
        self._threshold = float(thr)
        self.update()

    def clear(self) -> None:
        self._samples.clear()
        self._current = None
        self.update()

    def add_sample(self, sim: float) -> None:
        if sim < 0:
            self._current = None
        else:
            self._current = sim
            self._samples.append(sim)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        width, height = self.width(), self.height()
        painter.fillRect(0, 0, width, height, QColor(SURFACE))
        painter.setPen(QColor(BORDER))
        painter.drawRect(0, 0, width - 1, height - 1)

        pad_l, pad_r, pad_t, pad_b = 8, 8, 22, 18
        plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
        counts = [0] * self._BINS
        for sample in self._samples:
            counts[min(self._BINS - 1, max(0, int(sample * self._BINS)))] += 1
        peak = max(counts) if counts else 0

        bar_w = plot_w / self._BINS
        for index, count in enumerate(counts):
            if count == 0 or peak == 0:
                continue
            bar_h = (count / peak) * plot_h
            x = pad_l + index * bar_w
            y = pad_t + (plot_h - bar_h)
            center = (index + 0.5) / self._BINS
            color = QColor(SUCCESS) if center >= self._threshold else QColor(BORDER_CONTROL)
            painter.fillRect(int(x) + 1, int(y), max(1, int(bar_w) - 1), int(bar_h), color)

        threshold_x = pad_l + self._threshold * plot_w
        painter.setPen(QColor(DANGER))
        painter.drawLine(int(threshold_x), pad_t, int(threshold_x), pad_t + plot_h)
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(pad_l, 14, tr("hist_title"))
        current = (
            tr("hist_current", sim=self._current)
            if self._current is not None
            else tr("hist_no_face")
        )
        painter.drawText(
            pad_l,
            height - 5,
            f"{current}    {tr('hist_threshold', thr=self._threshold)}",
        )
        painter.end()


class ResizeHandle(QWidget):
    def __init__(self, parent, edges, cursor):
        super().__init__(parent)
        self.edges = edges
        self.setObjectName("resizeHandle")
        self.setCursor(cursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemResize(self.edges):
                event.accept()
                return
        super().mousePressEvent(event)


class CaptionButton(QPushButton):
    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.setFixedSize(46, 32)
        self.setFlat(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setObjectName("windowCloseButton" if kind == "close" else "windowButton")

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        color = (
            QColor(ON_ACCENT)
            if self.kind == "close" and self.underMouse()
            else QColor(TEXT_SECONDARY)
        )
        painter.setPen(color)
        cx = self.width() // 2
        cy = self.height() // 2
        if self.kind == "min":
            painter.drawLine(cx - 5, cy + 1, cx + 5, cy + 1)
        elif self.kind == "max":
            painter.drawRect(cx - 5, cy - 5, 10, 10)
        elif self.kind == "restore":
            painter.drawRect(cx - 3, cy - 5, 8, 8)
            painter.drawRect(cx - 6, cy - 2, 8, 8)
        else:
            painter.drawLine(cx - 5, cy - 5, cx + 5, cy + 5)
            painter.drawLine(cx + 5, cy - 5, cx - 5, cy + 5)
        painter.end()
