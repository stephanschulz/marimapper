"""Generic FTDI USB-DMX (raw 250k DMX512) — same as ofxGenericDmx DMX_DEVICE_RAW."""

from __future__ import annotations

from pyftdi.ftdi import Ftdi

# FTDI USB IDs used by ofxGenericDmx (FtdiDevice.cpp)
FTDI_VENDOR_ID = 0x0403

# Map common FTDI product IDs to pyftdi URL product codes (see Ftdi.show_devices).
FTDI_PRODUCT_CODES: dict[int, str] = {
    0x6001: "232",  # FT232R
    0x6010: "2232",  # FT2232H
    0x6011: "4232",  # FT4232H
    0x6014: "232h",  # FT232H
    0x6015: "230x",  # FT230X
}

DMX_BAUDRATE = 250_000
DMX_START_CODE = 0


def list_ftdi_devices() -> list[tuple[str, str]]:
    """Return (pyftdi_url, label) for each attached FTDI interface."""
    devices: list[tuple[str, str]] = []
    try:
        listed = Ftdi.list_devices()
    except Exception:
        return devices

    if not listed:
        return devices

    for descriptor, interface in listed:
        if descriptor.vid != FTDI_VENDOR_ID:
            continue
        product = FTDI_PRODUCT_CODES.get(descriptor.pid, f"{descriptor.pid:04x}")
        serial = descriptor.sn or ""
        url = f"ftdi://ftdi:{product}:{serial}/{interface}"
        label = descriptor.description or "FTDI device"
        if serial:
            label = f"{label} ({serial})"
        devices.append((url, label))
    return devices


def build_ftdi_url(descriptor, interface: int) -> str:
    product = FTDI_PRODUCT_CODES.get(descriptor.pid, f"{descriptor.pid:04x}")
    serial = descriptor.sn or ""
    return f"ftdi://ftdi:{product}:{serial}/{interface}"


class GenericUsbOutput:
    """
    Raw DMX over FTDI (250000 8N2, break + frame).

    Matches ofxGenericDmx ``DmxRawDevice`` / ``DMX_DEVICE_RAW``.
    """

    def __init__(self, url: str | None = None, channels: int = 512):
        self.url = url
        self.channels = max(24, min(512, channels))
        self.levels = bytearray(self.channels)
        self._ftdi: Ftdi | None = None
        self.device_name = ""

    @property
    def is_connected(self) -> bool:
        return self._ftdi is not None

    def connect(self, url: str | None = None) -> bool:
        target = (url or self.url or "").strip()
        if not target:
            devices = list_ftdi_devices()
            if not devices:
                return False
            target = devices[0][0]

        self.disconnect()
        ftdi = Ftdi()
        try:
            ftdi.open_from_url(target)
            ftdi.reset()
            ftdi.set_baudrate(DMX_BAUDRATE)
            ftdi.set_line_property(8, 2, "N")
            ftdi.set_flowctrl("")
            ftdi.set_rts(False)
            ftdi.purge_buffers()
        except Exception:
            try:
                ftdi.close()
            except Exception:
                pass
            return False

        self._ftdi = ftdi
        self.url = target
        self.device_name = target
        return True

    def disconnect(self) -> None:
        if self._ftdi is not None:
            try:
                self.all_off()
                self.send()
            except OSError:
                pass
            try:
                self._ftdi.close()
            except Exception:
                pass
        self._ftdi = None

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

    def build_frame(self) -> bytes:
        """DMX512 frame: start code + channel data (513 bytes)."""
        return bytes([DMX_START_CODE]) + bytes(self.levels)

    def send(self) -> None:
        if not self.is_connected:
            raise OSError("Generic USB DMX device not connected")
        frame = self.build_frame()
        self._ftdi.set_break(True)
        self._ftdi.set_break(False)
        self._ftdi.write_data(frame)

    def all_off(self) -> None:
        self.set_all(0)
