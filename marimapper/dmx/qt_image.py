"""Convert OpenCV frames for Qt widgets (main thread only)."""

from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtGui import QImage, QPixmap


def bgr_frame_to_qpixmap(frame: np.ndarray) -> QPixmap:
    if frame is None or frame.size == 0:
        return QPixmap()
    if len(frame.shape) == 2:
        height, width = frame.shape
        bytes_per_line = width
        image = QImage(
            frame.data, width, height, bytes_per_line, QImage.Format_Grayscale8
        )
    else:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, _channels = rgb.shape
        bytes_per_line = 3 * width
        image = QImage(
            rgb.data, width, height, bytes_per_line, QImage.Format_RGB888
        )
    return QPixmap.fromImage(image.copy())
