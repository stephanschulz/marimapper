# Art-Net

Art-Net output using [stupidArtnet](https://pypi.org/project/stupidartnet/) (same stack as `artnet_gui.py` in the DMX tester app).

## DMX tester GUI

```bash
marimapper_dmx_gui
```

Select **Art-Net**, set target IP and universe range, optionally enable **ArtSync**.

## MariMapper scan backend

```bash
marimapper artnet --help
marimapper artnet --server 192.168.1.255 --broadcast \
  --det_min_channel 1 --det_max_channel 50 --det_universe 0
```

LED index `0` turns on DMX channel `det_min_channel` on `det_universe`. Use `--artsync` if your nodes expect synchronized output.

The DMX GUI (`marimapper_dmx_gui`) has the same settings under **Camera detection (DMX ID)**.

## Network setup

See comments in the DMX tester `dmx_handler.h` for a typical isolated Ethernet setup (no Wi‑Fi, static IP, broadcast subnet).
