# Enttec DMX USB Pro

USB DMX output using the Enttec Pro serial protocol (same as `ofxDmx` in the DMX tester app).

## DMX tester GUI

```bash
marimapper_dmx_gui
```

Choose **Enttec USB Pro**, pick your serial port, and use the channel visualizer / chase / fade tools.

For FTDI chips using raw 250k DMX (not the Enttec packet protocol), use **Generic USB** instead — see [GenericUsb.md](GenericUsb.md).

## MariMapper scan backend

```bash
marimapper enttec --help
marimapper enttec --fixture_count 100 --channels_per_fixture 1 --start_channel 1
```

`--port` is optional; the first available USB serial device is used if omitted.

## macOS notes

- Install drivers if the device does not appear under **Refresh ports** in the GUI.
- List ports: `ls /dev/tty.usb* /dev/tty.usbserial*`
