import numpy as np

from marimapper.led_background import LedBackgroundSubtractor


def test_background_subtractor_finds_flash():
    sub = LedBackgroundSubtractor(threshold=30, alpha=0.9, min_change=5)
    dark = np.zeros((120, 160), dtype=np.uint8) + 20
    for _ in range(8):
        sub.update(dark)
    flash = dark.copy()
    flash[50:70, 70:90] = 220
    point = sub.find_led(flash)
    assert point is not None


def test_background_subtractor_ignores_static_scene():
    sub = LedBackgroundSubtractor(threshold=40, alpha=0.9)
    frame = np.zeros((80, 80), dtype=np.uint8) + 25
    for _ in range(10):
        sub.update(frame)
    assert sub.find_led(frame) is None
