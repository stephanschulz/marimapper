"""Camera preview with polygon ROI drawing and draggable vertices."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from marimapper.detection_roi import DetectionRoi
from marimapper.dmx.qt_image import bgr_frame_to_qpixmap

_VERTEX_HIT_PX = 12


class FramePreviewWidget(QWidget):
    """Read-only frame display (e.g. threshold view)."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background-color: #141414;")
        self._title = title
        self._pixmap: QPixmap | None = None

    def set_frame(self, frame) -> None:
        if frame is None:
            self._pixmap = None
        else:
            pixmap = bgr_frame_to_qpixmap(frame)
            self._pixmap = None if pixmap.isNull() else pixmap
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(20, 20, 20))
        if self._title:
            painter.setPen(QColor(180, 180, 180))
            painter.setFont(QFont("Helvetica", 10))
            painter.drawText(8, 16, self._title)

        if self._pixmap is None or self._pixmap.isNull():
            painter.setPen(QColor(120, 120, 120))
            painter.setFont(QFont("Helvetica", 12))
            painter.drawText(self.rect(), Qt.AlignCenter, self._title or "Preview")
            painter.end()
            return

        rect = RoiPreviewWidget._fit_rect(self._pixmap.size(), QRectF(self.rect()))
        painter.drawPixmap(rect.toRect(), self._pixmap)
        painter.end()


class ZoomableFramePreviewWidget(FramePreviewWidget):
    """Frame preview with scroll-wheel zoom centered on the cursor."""

    _MIN_ZOOM = 0.25
    _MAX_ZOOM = 12.0
    _ZOOM_STEP = 1.12

    def __init__(self, title: str = "", parent=None):
        super().__init__(title, parent)
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.setToolTip("Scroll to zoom (cursor-centered). Double-click to reset zoom.")

    def set_frame(self, frame) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        super().set_frame(frame)

    def reset_view(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()

    def _base_fit_rect(self) -> QRectF | None:
        if self._pixmap is None or self._pixmap.isNull():
            return None
        return RoiPreviewWidget._fit_rect(self._pixmap.size(), QRectF(self.rect()))

    def _display_rect(self) -> QRectF | None:
        base = self._base_fit_rect()
        if base is None or base.isEmpty():
            return None
        width = base.width() * self._zoom
        height = base.height() * self._zoom
        center = base.center() + self._pan
        return QRectF(center.x() - width / 2.0, center.y() - height / 2.0, width, height)

    def _norm_at_widget(self, wx: float, wy: float) -> tuple[float, float] | None:
        rect = self._display_rect()
        if rect is None or rect.width() <= 0 or rect.height() <= 0:
            return None
        return (
            (wx - rect.left()) / rect.width(),
            (wy - rect.top()) / rect.height(),
        )

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = self._ZOOM_STEP if delta > 0 else 1.0 / self._ZOOM_STEP
        new_zoom = max(self._MIN_ZOOM, min(self._MAX_ZOOM, self._zoom * factor))
        if abs(new_zoom - self._zoom) < 1e-6:
            return

        mouse = event.position()
        norm = self._norm_at_widget(mouse.x(), mouse.y())
        if norm is None:
            self._zoom = new_zoom
            self.update()
            event.accept()
            return

        nx, ny = norm
        base = self._base_fit_rect()
        assert base is not None
        new_w = base.width() * new_zoom
        new_h = base.height() * new_zoom
        new_cx = mouse.x() - nx * new_w + new_w / 2.0
        new_cy = mouse.y() - ny * new_h + new_h / 2.0
        self._pan = QPointF(new_cx - base.center().x(), new_cy - base.center().y())
        self._zoom = new_zoom
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(20, 20, 20))

        if self._pixmap is None or self._pixmap.isNull():
            painter.setPen(QColor(120, 120, 120))
            painter.setFont(QFont("Helvetica", 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._title or "Preview")
            painter.end()
            return

        rect = self._display_rect()
        if rect is None:
            painter.end()
            return

        painter.drawPixmap(rect.toRect(), self._pixmap)
        if self._zoom != 1.0:
            painter.setPen(QColor(140, 140, 140))
            painter.setFont(QFont("Helvetica", 10))
            painter.drawText(8, 16, f"Zoom {self._zoom:.0%} — double-click to reset")
        painter.end()


class LabeledPreview(QWidget):
    def __init__(self, title: str, preview: QWidget, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        label = QLabel(title)
        label.setStyleSheet("color: #bbb; font-size: 11px;")
        layout.addWidget(label)
        layout.addWidget(preview, stretch=1)


class RoiPreviewWidget(QWidget):
    """Shows the camera frame; draw or drag polygon ROI vertices."""

    roi_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background-color: #141414;")
        self.setMouseTracking(True)

        self._pixmap: QPixmap | None = None
        self._roi = DetectionRoi()
        self._draft: list[tuple[float, float]] = []
        self._drawing = False
        self._hover: tuple[float, float] | None = None
        self._drag_index: int | None = None

    def roi(self) -> DetectionRoi:
        return self._roi

    def set_roi(self, roi: DetectionRoi) -> None:
        self._roi = DetectionRoi(points=list(roi.points))
        self._draft.clear()
        self._hover = None
        self._drag_index = None
        self.update()
        self.roi_changed.emit(self._roi)

    def is_drawing(self) -> bool:
        return self._drawing

    def start_drawing(self) -> None:
        self._drawing = True
        self._draft.clear()
        self._hover = None
        self._drag_index = None
        self.update()

    def cancel_drawing(self) -> None:
        self._drawing = False
        self._draft.clear()
        self._hover = None
        self._drag_index = None
        self.unsetCursor()
        self.update()

    def clear_roi(self) -> None:
        self._drawing = False
        self._draft.clear()
        self._hover = None
        self._drag_index = None
        self._roi.clear()
        self.unsetCursor()
        self.update()
        self.roi_changed.emit(self._roi)

    def close_polygon(self) -> bool:
        if len(self._draft) < 3:
            return False
        self._roi = DetectionRoi(points=list(self._draft))
        self._draft.clear()
        self._drawing = False
        self._hover = None
        self._drag_index = None
        self.update()
        self.roi_changed.emit(self._roi)
        return True

    def set_frame(self, frame) -> None:
        pixmap = bgr_frame_to_qpixmap(frame)
        if pixmap.isNull():
            return
        self._pixmap = pixmap
        self.update()

    def _image_rect(self) -> QRectF | None:
        if self._pixmap is None or self._pixmap.isNull():
            return None
        return self._fit_rect(self._pixmap.size(), QRectF(self.rect()))

    @staticmethod
    def _fit_rect(source_size, target: QRectF) -> QRectF:
        if source_size.width() <= 0 or source_size.height() <= 0:
            return QRectF()
        scale = min(
            target.width() / source_size.width(),
            target.height() / source_size.height(),
        )
        w = source_size.width() * scale
        h = source_size.height() * scale
        x = target.x() + (target.width() - w) / 2.0
        y = target.y() + (target.height() - h) / 2.0
        return QRectF(x, y, w, h)

    def _widget_to_norm(self, wx: float, wy: float) -> tuple[float, float] | None:
        rect = self._image_rect()
        if rect is None or rect.width() <= 0 or rect.height() <= 0:
            return None
        x = (wx - rect.left()) / rect.width()
        y = (wy - rect.top()) / rect.height()
        return (max(0.0, min(1.0, x)), max(0.0, min(1.0, y)))

    def _norm_to_widget(self, nx: float, ny: float) -> QPointF:
        rect = self._image_rect()
        if rect is None:
            return QPointF()
        return QPointF(
            rect.left() + nx * rect.width(),
            rect.top() + ny * rect.height(),
        )

    def _vertex_at(self, wx: float, wy: float) -> int | None:
        if not self._roi.is_valid():
            return None
        for index, (nx, ny) in enumerate(self._roi.points):
            pt = self._norm_to_widget(nx, ny)
            if (pt.x() - wx) ** 2 + (pt.y() - wy) ** 2 <= _VERTEX_HIT_PX**2:
                return index
        return None

    def _emit_roi(self) -> None:
        self.roi_changed.emit(self._roi)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        wx, wy = event.position().x(), event.position().y()

        if self._drawing:
            norm = self._widget_to_norm(wx, wy)
            if norm is None:
                return
            self._draft.append(norm)
            self.update()
            return

        hit = self._vertex_at(wx, wy)
        if hit is not None:
            self._drag_index = hit
            self.setCursor(QCursor(Qt.ClosedHandCursor))
            return

    def mouseMoveEvent(self, event) -> None:
        wx, wy = event.position().x(), event.position().y()

        if self._drag_index is not None:
            norm = self._widget_to_norm(wx, wy)
            if norm is not None:
                points = list(self._roi.points)
                points[self._drag_index] = norm
                self._roi = DetectionRoi(points=points)
                self._emit_roi()
                self.update()
            return

        if self._drawing:
            self._hover = self._widget_to_norm(wx, wy)
            self.update()
            return

        if self._roi.is_valid() and self._vertex_at(wx, wy) is not None:
            self.setCursor(QCursor(Qt.OpenHandCursor))
        else:
            self.unsetCursor()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._drag_index is not None:
            self._drag_index = None
            self.unsetCursor()
            self._emit_roi()

    def mouseDoubleClickEvent(self, event) -> None:
        if self._drawing and event.button() == Qt.LeftButton:
            self.close_polygon()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(20, 20, 20))

        if self._pixmap is None or self._pixmap.isNull():
            painter.setPen(QColor(136, 136, 136))
            painter.setFont(QFont("Helvetica", 14))
            painter.drawText(self.rect(), Qt.AlignCenter, "Camera preview")
            painter.end()
            return

        rect = self._image_rect()
        if rect is None:
            painter.end()
            return

        painter.drawPixmap(rect.toRect(), self._pixmap)

        def draw_poly(
            points: list[tuple[float, float]],
            closed: bool,
            line_color: QColor,
            vertex_color: QColor,
        ) -> None:
            if not points:
                return
            widget_pts = [self._norm_to_widget(x, y) for x, y in points]
            painter.setPen(QPen(line_color, 2))
            for index in range(1, len(widget_pts)):
                painter.drawLine(widget_pts[index - 1], widget_pts[index])
            if closed and len(widget_pts) >= 3:
                painter.drawLine(widget_pts[-1], widget_pts[0])
            painter.setBrush(vertex_color)
            painter.setPen(QPen(vertex_color.darker(120), 1))
            for pt in widget_pts:
                painter.drawEllipse(pt, 6, 6)

        if self._roi.is_valid():
            draw_poly(
                self._roi.points,
                True,
                QColor(0, 255, 255),
                QColor(0, 200, 255),
            )

        if self._drawing:
            draft = list(self._draft)
            if self._hover is not None and draft:
                draft = draft + [self._hover]
            draw_poly(draft, False, QColor(255, 220, 0), QColor(255, 180, 0))
            painter.setPen(QColor(255, 220, 0))
            painter.setFont(QFont("Helvetica", 11))
            painter.drawText(
                8,
                20,
                "Click corners — double-click to finish (min 3 points)",
            )
        elif self._roi.is_valid():
            painter.setPen(QColor(160, 160, 160))
            painter.setFont(QFont("Helvetica", 10))
            painter.drawText(8, 16, "Drag cyan handles to adjust ROI")

        painter.end()
