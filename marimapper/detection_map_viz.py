"""Draw 2D LED maps on camera frames for GUI preview."""

from __future__ import annotations

import typing

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
    marker_size: int = 20,
    label_formatter: typing.Callable[[LED2D], str] | None = None,
    font_scale: float | None = None,
) -> np.ndarray:
    """Overlay all detected LEDs on a BGR or grayscale frame."""
    if len(image.shape) == 2:
        render_image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    else:
        render_image = image.copy()

    img_height, img_width = render_image.shape[:2]
    if font_scale is None:
        font_scale = max(0.45, min(img_width, img_height) / 1400.0)
    thickness = max(1, int(round(font_scale * 2)))

    for led in sorted(leds, key=lambda item: item.led_id):
        point = led.point
        # Skip placeholder rows for LEDs that were scanned but not detected.
        if point.u() < 0.0 or point.v() < 0.0:
            continue
        u_abs, v_abs = normalized_to_pixel(
            point.u(), point.v(), img_width, img_height
        )
        cv2.drawMarker(
            render_image,
            (u_abs, v_abs),
            (0, 255, 0),
            markerType=cv2.MARKER_CROSS,
            markerSize=marker_size,
            thickness=1,
        )
        if show_labels:
            text = (
                label_formatter(led)
                if label_formatter is not None
                else str(led.led_id)
            )
            cv2.putText(
                render_image,
                text,
                (u_abs + 6, v_abs - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                (255, 255, 255),
                thickness,
                cv2.LINE_AA,
            )

    return render_image


def dmx_channel_for_led(
    led_id: int, *, min_channel: int = 1, channels_per_fixture: int = 1
) -> int:
    """Return 1-based DMX channel for a scan LED index."""
    return min_channel + led_id * channels_per_fixture


def draw_led_map_with_dmx(
    image: np.ndarray,
    leds: list[LED2D],
    *,
    min_channel: int = 1,
    channels_per_fixture: int = 1,
    **kwargs,
) -> np.ndarray:
    """Overlay LEDs with crosshairs and 1-based DMX channel labels."""

    def label(led: LED2D) -> str:
        return str(
            dmx_channel_for_led(
                led.led_id,
                min_channel=min_channel,
                channels_per_fixture=channels_per_fixture,
            )
        )

    return draw_led_map(image, leds, label_formatter=label, **kwargs)


def draw_led_map_from_points(
    image: np.ndarray,
    points: list[tuple[int, Point2D]],
    **kwargs,
) -> np.ndarray:
    leds = [LED2D(led_id, 0, point) for led_id, point in points]
    return draw_led_map(image, leds, **kwargs)
