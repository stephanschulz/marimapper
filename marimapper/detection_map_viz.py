"""Draw 2D LED maps on camera frames for GUI preview."""

from __future__ import annotations

import cv2
import numpy as np

from marimapper.led import LED2D, Point2D


def normalized_to_pixel(u: float, v: float, img_width: int, img_height: int) -> tuple[int, int]:
    v_offset = (img_width - img_height) / 2.0
    u_abs = int(u * img_width)
    v_abs = int(v * img_width - v_offset)
    return u_abs, v_abs


def make_map_canvas(width: int = 640, height: int = 480) -> np.ndarray:
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    canvas[:] = (20, 20, 20)
    return canvas


def draw_led_map(
    image: np.ndarray,
    leds: list[LED2D],
    *,
    show_labels: bool = True,
    marker_size: int = 24,
) -> np.ndarray:
    """Overlay all detected LEDs on a BGR or grayscale frame."""
    if len(image.shape) == 2:
        render_image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    else:
        render_image = image.copy()

    img_height, img_width = render_image.shape[:2]

    for led in sorted(leds, key=lambda item: item.led_id):
        point = led.point
        if point.contours:
            cv2.drawContours(render_image, point.contours, -1, (255, 120, 0), 1)

        u_abs, v_abs = normalized_to_pixel(
            point.u(), point.v(), img_width, img_height
        )
        cv2.drawMarker(
            render_image,
            (u_abs, v_abs),
            (0, 255, 0),
            markerType=cv2.MARKER_CROSS,
            markerSize=marker_size,
            thickness=2,
        )
        if show_labels:
            cv2.putText(
                render_image,
                str(led.led_id),
                (u_abs + 6, v_abs - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

    return render_image


def draw_led_map_from_points(
    image: np.ndarray,
    points: list[tuple[int, Point2D]],
    **kwargs,
) -> np.ndarray:
    leds = [LED2D(led_id, 0, point) for led_id, point in points]
    return draw_led_map(image, leds, **kwargs)
