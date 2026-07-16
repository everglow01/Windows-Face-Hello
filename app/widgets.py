from __future__ import annotations

from collections import deque

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QWidget

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
