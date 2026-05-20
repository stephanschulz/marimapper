import numpy as np

from marimapper.detection_preview import build_threshold_view
from marimapper.detection_roi import DetectionRoi


def test_build_threshold_view_higher_is_stricter():
    gray = np.full((50, 50), 100, dtype=np.uint8)
    image = np.stack([gray, gray, gray], axis=-1)
    low = build_threshold_view(image, 50, use_frame_diff=False)
    high = build_threshold_view(image, 150, use_frame_diff=False)
    assert low.mean() > high.mean()

    roi = DetectionRoi(points=[(0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (0.0, 0.5)])
    masked = build_threshold_view(image, 50, roi=roi, use_frame_diff=False)
    assert masked[0:25, 40:50].mean() == 0
