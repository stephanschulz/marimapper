import numpy as np

from marimapper.detection_map_viz import draw_led_map, normalized_to_pixel
from marimapper.led import LED2D, Point2D


def test_normalized_to_pixel_square():
    u_abs, v_abs = normalized_to_pixel(0.5, 0.5, 100, 100)
    assert u_abs == 50
    assert v_abs == 50


def test_draw_led_map_marks_pixels():
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    leds = [LED2D(3, 0, Point2D(0.5, 0.5))]
    overlay = draw_led_map(image, leds, show_labels=False)
    assert overlay.shape == (100, 100, 3)
    assert overlay.any()


def test_draw_led_map_with_dmx_labels():
    from marimapper.detection_map_viz import draw_led_map_with_dmx

    image = np.zeros((100, 100, 3), dtype=np.uint8)
    leds = [LED2D(2, 0, Point2D(0.5, 0.5))]
    overlay = draw_led_map_with_dmx(
        image, leds, min_channel=10, channels_per_fixture=3
    )
    assert overlay.shape == (100, 100, 3)
    assert overlay.any()
