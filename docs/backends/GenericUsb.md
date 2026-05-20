# Generic USB (FTDI raw DMX)

Raw DMX512 over FTDI USB, matching **Generic USB** in the OpenFrameworks DMX tester (`ofxGenericDmx` / `DMX_DEVICE_RAW`).

- 250000 baud, 8N2
- DMX break + start code `0` + up to 512 channels
- Uses [pyftdi](https://eblot.github.io/pyftdi/) (libusb), not the macOS VCP serial driver

## DMX tester GUI

```bash
marimapper_dmx_gui
```

Choose **Generic USB**, click **Refresh devices**, pick your FTDI interface.

## MariMapper scan backend

```bash
marimapper generic_usb --help
marimapper generic_usb --fixture_count 100 --start_channel 1
```

`--url` is optional (first FTDI device is used if omitted). Example:

```bash
marimapper generic_usb --url 'ftdi://ftdi:232:B001QNTV/1'
```

List URLs from Python:

```python
from marimapper.dmx import list_ftdi_devices
print(list_ftdi_devices())
```

## macOS notes

If the device appears as `/dev/tty.usbserial-*` but **Generic USB** finds nothing, the FTDI **VCP driver** may be claiming the chip. The OF addon readme suggests uninstalling the VCP driver so libftdi/pyftdi can access the device directly.

See [ofxGenericDmx OS notes](https://github.com/stephanschulz/ofxGenericDmx#osx).
