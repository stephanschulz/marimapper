"""LED detection via averaged background subtraction (not global threshold only)."""

from __future__ import annotations

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import cv2
import numpy as np

if TYPE_CHECKING:
    from marimapper.detection_roi import DetectionRoi

from marimapper.led import Point2D


def image_to_gray(image: np.ndarray) -> np.ndarray:
    if len(image.shape) > 2:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


class LedBackgroundSubtractor:
    """
    Exponential moving-average background; detect bright flashes vs that model.

    Used while DMX is off to learn the scene, then diff when a single LED turns on.
    """

    def __init__(
        self,
        threshold: int = 40,
        alpha: float = 0.92,
        blur_size: int = 5,
        min_change: int = 8,
        roi: DetectionRoi | None = None,
    ):
        self.threshold = threshold
        self.alpha = alpha
        self.blur_size = blur_size if blur_size % 2 == 1 else blur_size + 1
        self.min_change = min_change
        self.roi = roi
        self._background: np.ndarray | None = None

    def reset(self) -> None:
        self._background = None

    def update(self, image: np.ndarray) -> None:
        """Blend frame into background (call while LEDs are off)."""
        gray = image_to_gray(image).astype(np.float32)
        if self._background is None:
            self._background = gray.copy()
            return
        self._background = (
            self.alpha * self._background + (1.0 - self.alpha) * gray
        )

    def difference_image(self, image: np.ndarray) -> np.ndarray:
        gray = image_to_gray(image).astype(np.float32)
        if self._background is None:
            return np.zeros_like(gray, dtype=np.uint8)
        diff = gray - self._background
        diff = np.clip(diff, 0, 255).astype(np.uint8)
        if self.blur_size > 1:
            diff = cv2.GaussianBlur(diff, (self.blur_size, self.blur_size), 0)
        return diff

    def find_led(self, image: np.ndarray) -> Optional[Point2D]:
        from marimapper.detector import find_led_in_image

        diff = self.difference_image(image)
        if self.roi is not None and self.roi.is_valid():
            diff = self.roi.apply_to_image(diff)
        if int(diff.max()) < self.min_change:
            return None
        return find_led_in_image(diff, self.threshold)
