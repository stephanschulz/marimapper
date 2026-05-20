"""Polygon region-of-interest for LED detection (normalized image coordinates)."""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class DetectionRoi:
    """
    Closed polygon in normalized image coordinates.

    Each point is (x, y) with 0..1 relative to frame width and height.
    """

    points: list[tuple[float, float]] = field(default_factory=list)

    def is_valid(self) -> bool:
        return len(self.points) >= 3

    def clear(self) -> None:
        self.points.clear()

    def pixel_polygon(self, width: int, height: int) -> np.ndarray:
        pts = np.array(
            [
                [int(max(0, min(1, x)) * (width - 1)), int(max(0, min(1, y)) * (height - 1))]
                for x, y in self.points
            ],
            dtype=np.int32,
        )
        return pts.reshape((-1, 1, 2))

    def mask(self, height: int, width: int) -> np.ndarray:
        mask = np.zeros((height, width), dtype=np.uint8)
        if self.is_valid():
            cv2.fillPoly(mask, [self.pixel_polygon(width, height)], 255)
        return mask

    def apply_to_image(self, image: np.ndarray) -> np.ndarray:
        if not self.is_valid():
            return image
        height, width = image.shape[:2]
        mask = self.mask(height, width)
        if len(image.shape) == 3:
            masked = image.copy()
            masked[mask == 0] = 0
            return masked
        return cv2.bitwise_and(image, mask)

    def draw_overlay(
        self,
        image: np.ndarray,
        *,
        color: tuple[int, int, int] = (0, 255, 255),
        thickness: int = 2,
    ) -> np.ndarray:
        if len(image.shape) == 2:
            out = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            out = image.copy()
        if not self.points:
            return out
        height, width = out.shape[:2]
        pts = self.pixel_polygon(width, height)
        if len(self.points) >= 2:
            cv2.polylines(out, [pts], self.is_valid(), color, thickness, cv2.LINE_AA)
        for x, y in self.points:
            px = int(max(0, min(1, x)) * (width - 1))
            py = int(max(0, min(1, y)) * (height - 1))
            cv2.circle(out, (px, py), 4, color, -1, cv2.LINE_AA)
        return out

    def to_list(self) -> list[list[float]]:
        return [[float(x), float(y)] for x, y in self.points]

    @classmethod
    def from_list(cls, data) -> DetectionRoi:
        if not data:
            return cls()
        points = []
        for item in data:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                points.append((float(item[0]), float(item[1])))
        return cls(points=points)
