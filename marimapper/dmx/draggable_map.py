"""Map preview with draggable LED crosshairs."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy

from marimapper.dmx.qt_image import bgr_frame_to_qpixmap
from marimapper.dmx.roi_preview import RoiPreviewWidget, ZoomableFramePreviewWidget
from marimapper.file_tools import is_led_missing
from marimapper.led import LED2D, Point2D

_HANDLE_HIT_PX = 12
_HANDLE_RADIUS = 7


class DraggableLedMapWidget(ZoomableFramePreviewWidget):
    """Zoomable preview that lets the user drag individual LED crosshairs."""

    led_grabbed = Signal(int)
    led_moved = Signal(int, float, float)
    led_released = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._leds: list[LED2D] = []
        self._image_size: tuple[int, int] | None = None  # (w, h) of source frame
        self._drag_led_id: int | None = None
        self._min_channel: int = 1
        self._channels_per_fixture: int = 1
        self.setToolTip(
            "Drag a crosshair to fire its DMX channel at 255. "
            "Scroll to zoom (cursor-centered). Double-click to reset zoom."
        )

    def set_dmx_mapping(self, min_channel: int, channels_per_fixture: int) -> None:
        self._min_channel = max(1, int(min_channel))
        self._channels_per_fixture = max(1, int(channels_per_fixture))
        self.update()

    def _dmx_channel(self, led_id: int) -> int:
        return self._min_channel + led_id * self._channels_per_fixture

    # ---- public API --------------------------------------------------------

    def set_map(self, frame, leds: list[LED2D]) -> None:
        if frame is None:
            self._pixmap = None
            self._image_size = None
        else:
            pixmap = bgr_frame_to_qpixmap(frame)
            if pixmap.isNull():
                self._pixmap = None
                self._image_size = None
            else:
                self._pixmap = pixmap
                self._image_size = (pixmap.width(), pixmap.height())
        self._leds = list(leds)
        # Reset view so a new map fits nicely.
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._drag_led_id = None
        self.update()

    def set_live_frame(self, frame) -> None:
        """Swap only the background bitmap — keep LEDs, zoom, and pan."""
        if frame is None or getattr(frame, "size", 0) == 0:
            return
        pixmap = bgr_frame_to_qpixmap(frame)
        if pixmap.isNull():
            return
        self._pixmap = pixmap
        self._image_size = (pixmap.width(), pixmap.height())
        self.update()

    def clear(self) -> None:
        self.set_map(None, [])

    def leds(self) -> list[LED2D]:
        return list(self._leds)

    # ---- geometry helpers --------------------------------------------------

    def _norm_to_widget_uv(self, u: float, v: float) -> QPointF | None:
        rect = self._display_rect()
        if rect is None or self._image_size is None:
            return None
        img_w, img_h = self._image_size
        if img_w <= 0 or img_h <= 0:
            return None
        v_offset = (img_w - img_h) / 2.0
        px = u * img_w
        py = v * img_w - v_offset
        return QPointF(
            rect.left() + (px / img_w) * rect.width(),
            rect.top() + (py / img_h) * rect.height(),
        )

    def _widget_to_uv(self, wx: float, wy: float) -> tuple[float, float] | None:
        rect = self._display_rect()
        if rect is None or rect.width() <= 0 or rect.height() <= 0:
            return None
        if self._image_size is None:
            return None
        img_w, img_h = self._image_size
        if img_w <= 0 or img_h <= 0:
            return None
        # widget -> pixel coords in source image
        px = (wx - rect.left()) / rect.width() * img_w
        py = (wy - rect.top()) / rect.height() * img_h
        v_offset = (img_w - img_h) / 2.0
        u = px / img_w
        v = (py + v_offset) / img_w
        return u, v

    def _led_at(self, wx: float, wy: float) -> int | None:
        for led in self._leds:
            if is_led_missing(led):
                continue
            pt = self._norm_to_widget_uv(led.point.u(), led.point.v())
            if pt is None:
                continue
            if (pt.x() - wx) ** 2 + (pt.y() - wy) ** 2 <= _HANDLE_HIT_PX**2:
                return led.led_id
        return None

    def _update_led_position(self, led_id: int, u: float, v: float) -> None:
        for index, led in enumerate(self._leds):
            if led.led_id == led_id:
                self._leds[index] = LED2D(led.led_id, led.view_id, Point2D(u, v))
                return

    # ---- mouse events ------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or not self._leds:
            super().mousePressEvent(event)
            return
        wx, wy = event.position().x(), event.position().y()
        hit = self._led_at(wx, wy)
        if hit is not None:
            self._drag_led_id = hit
            self.setCursor(QCursor(Qt.ClosedHandCursor))
            self.led_grabbed.emit(hit)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        wx, wy = event.position().x(), event.position().y()
        if self._drag_led_id is not None:
            uv = self._widget_to_uv(wx, wy)
            if uv is not None:
                u, v = uv
                self._update_led_position(self._drag_led_id, u, v)
                self.led_moved.emit(self._drag_led_id, u, v)
                self.update()
            event.accept()
            return

        if self._led_at(wx, wy) is not None:
            self.setCursor(QCursor(Qt.OpenHandCursor))
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._drag_led_id is not None:
            released_id = self._drag_led_id
            self._drag_led_id = None
            self.unsetCursor()
            self.led_released.emit(released_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ---- rendering ---------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(20, 20, 20))

        if self._pixmap is None or self._pixmap.isNull():
            painter.setPen(QColor(120, 120, 120))
            painter.setFont(QFont("Helvetica", 12))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "Run a scan to see a map."
            )
            painter.end()
            return

        rect = self._display_rect()
        if rect is None:
            painter.end()
            return
        painter.drawPixmap(rect.toRect(), self._pixmap)

        painter.setRenderHint(QPainter.Antialiasing, True)
        font = QFont("Helvetica", 10)
        painter.setFont(font)
        for led in self._leds:
            if is_led_missing(led):
                continue
            pt = self._norm_to_widget_uv(led.point.u(), led.point.v())
            if pt is None:
                continue
            is_dragging = self._drag_led_id == led.led_id
            color = QColor(255, 200, 0) if is_dragging else QColor(0, 230, 0)
            pen = QPen(color, 2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            # Crosshair
            r = _HANDLE_RADIUS
            painter.drawLine(
                QPointF(pt.x() - r, pt.y()), QPointF(pt.x() + r, pt.y())
            )
            painter.drawLine(
                QPointF(pt.x(), pt.y() - r), QPointF(pt.x(), pt.y() + r)
            )
            painter.drawEllipse(pt, r, r)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(
                pt + QPointF(r + 2, -r), str(self._dmx_channel(led.led_id))
            )

        if self._zoom != 1.0:
            painter.setPen(QColor(140, 140, 140))
            painter.drawText(
                8, 16, f"Zoom {self._zoom:.0%} — double-click to reset"
            )
        painter.end()

    # Keep base class fit_rect helper accessible.
    @staticmethod
    def _fit_rect(source_size, target: QRectF) -> QRectF:
        return RoiPreviewWidget._fit_rect(source_size, target)
