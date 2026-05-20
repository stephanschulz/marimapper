import numpy as np

from marimapper.detection_roi import DetectionRoi
from marimapper.detector import find_led_in_image


def test_roi_masks_outside_detection():
    frame = np.zeros((100, 100), dtype=np.uint8)
    frame[70:80, 70:80] = 200
    roi = DetectionRoi(points=[(0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (0.0, 0.5)])
    assert find_led_in_image(frame, threshold=128) is not None
    assert find_led_in_image(frame, threshold=128, roi=roi) is None

    frame2 = np.zeros((100, 100), dtype=np.uint8)
    frame2[10:20, 10:20] = 200
    assert find_led_in_image(frame2, threshold=128, roi=roi) is not None


def test_roi_serialization():
    roi = DetectionRoi(points=[(0.1, 0.2), (0.9, 0.2), (0.5, 0.9)])
    restored = DetectionRoi.from_list(roi.to_list())
    assert restored.points == roi.points
    assert restored.is_valid()
