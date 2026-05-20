"""Build the thresholded view shown beside the live camera preview."""

from __future__ import annotations

import cv2
import numpy as np

from marimapper.detection_roi import DetectionRoi
from marimapper.led_background import LedBackgroundSubtractor, image_to_gray


def build_threshold_view(
    image: np.ndarray,
    threshold: int,
    *,
    roi: DetectionRoi | None = None,
    use_frame_diff: bool = False,
    subtractor: LedBackgroundSubtractor | None = None,
) -> np.ndarray:
    """
    Pixels at or above ``threshold`` stay bright; lower values become black.

    Higher threshold => only brighter blobs survive (matches ``find_led_in_image``).
    """
    if use_frame_diff and subtractor is not None:
        gray = subtractor.difference_image(image)
    else:
        gray = image_to_gray(image)

    if roi is not None and roi.is_valid():
        gray = roi.apply_to_image(gray)

    _, thresh = cv2.threshold(gray, threshold, 255, cv2.THRESH_TOZERO)
    return cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
