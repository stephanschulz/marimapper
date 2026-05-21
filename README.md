# DMX 2D LED calibration

This guide covers **single-camera 2D mapping**: turn each DMX channel on in turn, detect the LED in the camera, and save a CSV of pixel positions plus companion images.

This uses the **DMX GUI** (`marimapper_dmx_gui`), not the multi-view 3D `marimapper` scanner.

## Screenshots

**MariMapper DMX + Detection** — Art-Net / Enttec / Generic USB output, channel mapping, and test patterns:

![MariMapper DMX + Detection window](screenshots/MariMapper%20DMX%20+%20Detection.jpg)

**Camera — LED detection** — live preview, threshold view, ROI, and scan controls:

![Camera LED detection window](screenshots/Camera%20-%20LED%20detection.jpg)

**2D LED map** — browse saved scans, zoom the overlay, and inspect DMX channel assignments:

![2D LED map window](screenshots/2D%20LED%20map.jpg)

## What you need

- A **DMX output** device supported by the GUI:
  - **Art-Net** (Ethernet to a node or software)
  - **Enttec USB Pro** (serial DMX)
  - **Generic USB (FTDI)** (raw 250k DMX)
- A **webcam** or capture device (USB camera, built-in, etc.)
- Your fixtures wired so **one DMX channel = one identifiable LED** for the scan range you configure
- Dim ambient light — stray bright pixels cause missed or false detections

Backend-specific network/USB notes: [ArtNet.md](docs/backends/ArtNet.md), [Enttec.md](docs/backends/Enttec.md), [GenericUsb.md](docs/backends/GenericUsb.md).

## Install and launch

From this repo (recommended for development):

```bash
cd /Users/stephanschulz/Documents/cursor_ai/pixel-mapper
python -m venv .venv
source .venv/bin/activate
pip install -e .
marimapper_dmx_gui
```

Or install globally with [uv](https://github.com/astral-sh/uv) / pip as described in [README-marimapper.md](README-marimapper.md), then run:

```bash
marimapper_dmx_gui
```

On startup you get **two windows**:

1. **MariMapper DMX + Detection** — DMX output, channel mapping, test patterns
2. **Camera — LED detection** — live preview, ROI, single-LED test, 2D scan

Settings are saved to `marimapper/dmx/dmx_gui_settings.json` (camera, exposure, ROI, UVC on macOS, etc.).

Optional: verify the camera alone before calibrating:

```bash
marimapper_check_camera
```

Use `--device N` if the wrong camera is selected (same index as in the GUI dropdown).

## Step 1 — Configure DMX output

In the **DMX** window:

### Output device

| Mode | What to set |
|------|-------------|
| **Art-Net** | Target IP, universe start/end, optional **ArtSync** |
| **Enttec USB Pro** | Serial port (**Refresh ports** if empty) |
| **Generic USB** | FTDI device URL |

Use **All ON** / **Chase** to confirm fixtures respond before scanning.

### LED detection (DMX mapping)

Under **LED detection (DMX mapping)**:

| Setting | Meaning |
|---------|---------|
| **DMX channels** (min → max) | Channel range used for the scan, e.g. `1` to `50` |
| **Universe (Art-Net)** | Art-Net universe for detection output |
| **Channels / bulb** | DMX channels per fixture (usually `1` for one channel per pixel) |
| **DMX on level** | Brightness while a LED is on during test/scan (default `255`) |

**LED index → DMX channel:**

```
DMX channel = min_channel + (LED index × channels_per_fixture)
```

Example: min channel `1`, 1 channel per bulb → LED index `0` → DMX `1`, index `4` → DMX `5`.

The number of LEDs scanned = `(max_channel - min_channel + 1) / channels_per_fixture`.

Changing these values updates the **LED index** spinner range in the camera window.

## Step 2 — Set up the camera

In the **Camera** window:

1. **Camera** — pick the correct device; **Refresh** if needed.
2. **Exposure** — lower (more negative) for a darker image if the scene is too bright. On macOS, exposure control is limited; use the **UVC controls** panel (focus, gain, brightness, etc.) when available.
3. **Threshold** — brightness cutoff for detection (`0–255`). The **Threshold view** panel shows what the detector sees.
4. **Frame difference** — leave enabled for best results on a dark scene (learns background, detects flashes).

### Region of interest (optional)

If only part of the frame contains LEDs:

1. Click **Draw ROI**
2. Click polygon corners on the live preview
3. **Double-click** to close the polygon (minimum 3 points)
4. **Clear ROI** to use the full frame again

Detection runs only inside the ROI.

## Step 3 — Test one LED

Before a full scan:

1. Set **LED index** to a fixture you can see in the camera
2. The DMX window lights that channel (others at 0)
3. Click **Test this ID**

A green crosshair should appear on the LED in the preview when detection succeeds. Adjust exposure, threshold, or ROI if it fails.

While stepping indices, the status line shows the active **DMX channel** and **LED index**.

## Step 4 — Run the 2D scan

1. Mount the camera so it **does not move** during the scan
2. Turn off or cover unrelated light sources in view
3. Click **Run 2D detection scan**

The app steps through every LED index in range, flashes each channel, and detects its position. Progress appears in the status line (`Scan 12/50: LED 11 OK …`).

**Do not move the camera or fixtures during the scan.**

Click **Run 2D detection scan** again while a scan is running to stop it.

When finished, the **2D LED map** window opens automatically with the new capture selected.

## Step 5 — Review and export

### 2D LED map window

- **Map CSV** dropdown — browse past scans (newest first)
- **Mapped LEDs** — zoom with mouse wheel (cursor-centered), double-click to reset zoom
- Table columns: **Index**, **DMX**, **u**, **v** (normalized image coordinates, `0–1`)
- **Save CSV as…** — copy the map to another path (includes images and metadata)

### Output files

Scans are saved under the project **`scans/`** folder:

```
scans/
  led_map_2d_YYYYMMDD-HHMMSS.csv      # LED positions
  led_map_2d_YYYYMMDD-HHMMSS.png      # raw camera frame from the scan
  led_map_2d_YYYYMMDD-HHMMSS_map.png  # same frame + crosshairs + DMX labels
  led_map_2d_YYYYMMDD-HHMMSS.meta.json
```

**CSV format** (`index,dmx,u,v`):

```csv
index,dmx,u,v
0,1,0.986425,0.400617
1,2,0.802659,0.555862
```

- **index** — scan LED index (0-based)
- **dmx** — 1-based DMX channel used for that LED
- **u**, **v** — normalized coordinates in the camera image

**Meta JSON** stores `scan_total`, `min_channel`, and `channels_per_fixture` used when the scan was captured.

Older maps saved to `~/marimapper_maps/` are moved into `scans/` automatically on first open of the map window.

## Tips and troubleshooting

| Problem | Things to try |
|---------|----------------|
| No fixture response | Check DMX wiring, universe/IP/port, **All ON**, on level |
| LED not detected | Darken room, lower exposure, tune threshold, enable frame diff, draw ROI |
| Wrong LED lights | Fix min/max channel and channels-per-bulb; confirm fixture addressing |
| Too many false hits | Raise threshold, tighten ROI, remove reflections |
| Wrong camera | Change **Camera** dropdown or run `marimapper_check_camera --device N` |
| Scan finishes with 0 detections | Test individual IDs first; verify DMX and camera alignment |
| macOS exposure | Use UVC panel; manual camera app settings if needed ([README-marimapper.md](README-marimapper.md)) |

## DMX channel mapping reference

For a contiguous run of single-channel fixtures:

| LED index | DMX channel (1-based) |
|-----------|------------------------|
| 0 | `min_channel` |
| 1 | `min_channel + channels_per_fixture` |
| n | `min_channel + n × channels_per_fixture` |

Multi-channel fixtures: set **Channels / bulb** to match your patch so each logical LED still maps to the first channel of its fixture block.

## Related commands

CLI backends (multi-view 3D pipeline, not the GUI scan) use the same channel settings:

```bash
marimapper artnet --help
marimapper enttec --help
```

For this project's **2D DMX calibration workflow**, use **`marimapper_dmx_gui`** and the camera window scan.

## Acknowledgments

This project builds on **[MariMapper](https://github.com/TheMariday/marimapper)** by [TheMariday](https://github.com/TheMariday) — a tool that maps addressable LEDs into 2D and 3D space using a webcam. The DMX GUI, camera detection pipeline, and LED mapping core come from that upstream project.

- Upstream repository: [github.com/TheMariday/marimapper](https://github.com/TheMariday/marimapper)
- Upstream documentation: [README-marimapper.md](README-marimapper.md)

Thank you to the original developer and contributors for MariMapper.

## Licensing

This project inherits the upstream [GPLv3](LICENSE) license.

The TLDR is you can do anything you like with this as long as it's open source.
