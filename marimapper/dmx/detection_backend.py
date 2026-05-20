"""DMX backend used by the camera LED detector (one fixture / bulb at a time)."""

from __future__ import annotations

from time import sleep

from marimapper.dmx.artnet_output import ArtnetOutput
from marimapper.dmx.detection_config import DetectionDmxConfig
from marimapper.dmx.enttec_output import EnttecProOutput
from marimapper.dmx.generic_usb_output import GenericUsbOutput

DEVICE_ARTNET = "Art-Net"
DEVICE_ENTTEC = "Enttec USB Pro"
DEVICE_GENERIC = "Generic USB"


class DmxDetectionBackend:
    """Implements get_led_count / set_led for marimapper.detector."""

    def __init__(
        self,
        device_mode: str,
        config: DetectionDmxConfig,
        *,
        artnet: ArtnetOutput | None = None,
        enttec: EnttecProOutput | None = None,
        generic_usb: GenericUsbOutput | None = None,
    ):
        self.device_mode = device_mode
        self.config = config
        self.config.validate()
        self._artnet = artnet
        self._enttec = enttec
        self._generic_usb = generic_usb
        self._check_device()

    def _check_device(self) -> None:
        if self.device_mode == DEVICE_ARTNET and (
            self._artnet is None or self._artnet.universe_count < 1
        ):
            raise RuntimeError("Art-Net output not connected")
        if self.device_mode == DEVICE_ENTTEC and (
            self._enttec is None or not self._enttec.is_connected
        ):
            raise RuntimeError("Enttec output not connected")
        if self.device_mode == DEVICE_GENERIC and (
            self._generic_usb is None or not self._generic_usb.is_connected
        ):
            raise RuntimeError("Generic USB output not connected")

    def get_led_count(self) -> int:
        return self.config.fixture_count()

    def set_led(self, led_index: int, on: bool) -> None:
        value = self.config.on_level if on else 0
        base = self.config.channel_for_led(led_index)
        channels = [0] * 512
        for offset in range(self.config.channels_per_fixture):
            channel = base + offset
            if 0 <= channel < 512:
                channels[channel] = value

        for _ in range(self.config.burst_count):
            if self.device_mode == DEVICE_ARTNET:
                self._artnet.send_packets([bytearray(channels)])
            elif self.device_mode == DEVICE_ENTTEC:
                self._enttec.set_frame(channels)
                self._enttec.send()
            else:
                self._generic_usb.set_frame(channels)
                self._generic_usb.send()
            sleep(0.05)

    def all_off(self) -> None:
        channels = [0] * 512
        for _ in range(self.config.burst_count):
            if self.device_mode == DEVICE_ARTNET:
                self._artnet.send_packets([bytearray(channels)])
            elif self.device_mode == DEVICE_ENTTEC:
                self._enttec.set_frame(channels)
                self._enttec.send()
            else:
                self._generic_usb.set_frame(channels)
                self._generic_usb.send()
            sleep(0.02)
