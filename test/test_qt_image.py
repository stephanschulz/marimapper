import sys

import numpy as np
from PySide6.QtWidgets import QApplication

from marimapper.dmx.qt_image import bgr_frame_to_qpixmap


def test_bgr_frame_to_qpixmap():
    if QApplication.instance() is None:
        QApplication(sys.argv)
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    frame[:, :, 1] = 128
    pixmap = bgr_frame_to_qpixmap(frame)
    assert not pixmap.isNull()
    assert pixmap.width() == 64
