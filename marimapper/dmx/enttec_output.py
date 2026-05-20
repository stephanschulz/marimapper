"""Enttec DMX USB Pro output over serial (ofxDmx-compatible protocol)."""

from __future__ import annotations

import serial
import serial.tools.list_ports

DMX_PRO_START_MSG = 0x7E
DMX_PRO_END_MSG = 0xE7
DMX_PRO_SEND_PACKET = 6
DMX_START_CODE = 0


def list_serial_ports() -> list[tuple[str, str]]:
    return [(p.device, p.description or "") for p in serial.tools.list_ports.comports()]


class EnttecProOutput:
    """512-channel Enttec Pro / compatible USB-DMX interface."""

    def __init__(self, port: str | None = None, channels: int = 512, baud: int = 57600):
        self.port = port
        self.channels = max(24, min(512, channels))
        self.baud = baud
        self.levels = bytearray(self.channels)
        self._serial: serial.Serial | None = None
        self.device_name = ""

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def connect(self, port: str | None = None) -> bool:
        target = (port or self.port or "").strip()
        if not target:
            ports = list_serial_ports()
            if not ports:
                return False
            target = ports[0][0]

        self.disconnect()
        self._serial = serial.Serial(target, self.baud, timeout=0.1)
        self.port = target
        self.device_name = target
        return True

    def disconnect(self) -> None:
        if self._serial is not None:
            try:
                self.all_off()
                self.send()
            except OSError:
                pass
            if self._serial.is_open:
                self._serial.close()
        self._serial = None

    def set_channel(self, channel: int, value: int) -> None:
        """Set DMX channel (1–512)."""
        if channel < 1 or channel > self.channels:
            return
        self.levels[channel - 1] = max(0, min(255, value))

    def set_all(self, value: int) -> None:
        value = max(0, min(255, value))
        for index in range(self.channels):
            self.levels[index] = value

    def set_frame(self, data: bytearray | bytes) -> None:
        length = min(len(data), self.channels)
        self.levels[:length] = data[:length]

    def build_packet(self) -> bytes:
        data_size = self.channels + 1
        packet = bytearray(4 + data_size + 1)
        packet[0] = DMX_PRO_START_MSG
        packet[1] = DMX_PRO_SEND_PACKET
        packet[2] = data_size & 0xFF
        packet[3] = (data_size >> 8) & 0xFF
        packet[4] = DMX_START_CODE
        packet[5 : 5 + self.channels] = self.levels
        packet[-1] = DMX_PRO_END_MSG
        return bytes(packet)

    def send(self) -> None:
        if not self.is_connected:
            raise OSError("Enttec device not connected")
        self._serial.write(self.build_packet())

    def all_off(self) -> None:
        self.set_all(0)
