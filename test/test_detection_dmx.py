import pytest

from marimapper.dmx.detection_backend import DmxDetectionBackend, DEVICE_ARTNET
from marimapper.dmx.detection_config import DetectionDmxConfig


def test_detection_config_fixture_count():
    config = DetectionDmxConfig(min_channel=10, max_channel=19, channels_per_fixture=1)
    assert config.fixture_count() == 10
    assert config.channel_for_led(0) == 9
    assert config.channel_for_led(9) == 18


def test_detection_config_requires_divisible_range():
    config = DetectionDmxConfig(min_channel=1, max_channel=10, channels_per_fixture=4)
    with pytest.raises(ValueError):
        config.fixture_count()


class _FakeArtnet:
    universe_count = 1
    last_packets = None

    def send_packets(self, packets):
        self.last_packets = packets


def test_detection_backend_set_led_artnet():
    config = DetectionDmxConfig(min_channel=5, max_channel=7, channels_per_fixture=1, on_level=200)
    artnet = _FakeArtnet()
    backend = DmxDetectionBackend(DEVICE_ARTNET, config, artnet=artnet)
    assert backend.get_led_count() == 3
    backend.set_led(1, True)
    assert artnet.last_packets[0][5] == 200  # DMX channel 6 -> buffer index 5
