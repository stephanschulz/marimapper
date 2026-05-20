import numpy as np
import pytest

from marimapper.camera_exposure import (
    apply_software_gain,
    configure_camera_exposure,
    slider_to_gain,
)


def test_slider_to_gain():
    assert slider_to_gain(0) == 1.0
    assert slider_to_gain(-13) == pytest.approx(2**-13, rel=1e-6)
    assert slider_to_gain(-10) == pytest.approx(2**-10, rel=1e-6)


def test_apply_software_gain_darkens():
    frame = np.full((10, 10, 3), 200, dtype=np.uint8)
    out = apply_software_gain(frame, slider_to_gain(-10))
    assert out.mean() < frame.mean() * 0.2


def test_configure_file_camera_uses_software_for_dark(monkeypatch):
    class FakeCap:
        def set(self, *_args, **_kwargs):
            return False

        def read(self):
            return True, np.zeros((4, 4, 3), dtype=np.uint8)

    class FakeCam:
        device_id = 0
        device = FakeCap()
        exposure_status = ""

        def set_software_gain(self, gain):
            self.gain = gain

    cam = FakeCam()
    monkeypatch.setattr("marimapper.camera_exposure.sys.platform", "linux")
    monkeypatch.setattr(
        "marimapper.camera_exposure._darwin_try_hardware", lambda *a, **k: False
    )
    status, gain = configure_camera_exposure(cam, -10, dark=True)
    assert gain is not None and gain < 1.0
    assert "software" in status

