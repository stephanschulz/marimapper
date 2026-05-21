from __future__ import annotations

import json
import os
from marimapper.led import Point2D, LED3D, LED2D
import typing
from pathlib import Path


_HEADINGS_LEGACY = ["index", "u", "v"]
_HEADINGS = ["index", "dmx", "u", "v"]

# Sentinel for LEDs that were scanned but never detected by the camera.
# Stored in the CSV so every DMX channel has a row.
MISSING_LED_COORD = -1.0


def _dmx_channel_for_led(
    led_id: int, *, min_channel: int = 1, channels_per_fixture: int = 1
) -> int:
    return min_channel + led_id * channels_per_fixture


def is_led_missing(led: LED2D) -> bool:
    """True if this LED has no usable detection (placeholder for undetected scans)."""
    return led.point.u() < 0.0 or led.point.v() < 0.0


def fill_missing_leds(leds: list[LED2D], total: int) -> list[LED2D]:
    """
    Ensure one entry per led_id in ``[0, total)``.

    Detected LEDs are kept; gaps get ``Point2D(-1, -1)`` so every DMX channel
    has a row in the saved CSV. Pre-existing missing entries are preserved.
    """
    if total <= 0:
        return list(leds)
    by_id = {led.led_id: led for led in leds}
    result: list[LED2D] = []
    for led_id in range(total):
        existing = by_id.get(led_id)
        if existing is not None:
            result.append(existing)
        else:
            result.append(
                LED2D(led_id, 0, Point2D(MISSING_LED_COORD, MISSING_LED_COORD))
            )
    return result


def load_detections(filename: Path, view_id) -> typing.Optional[list[LED2D]]:

    if not os.path.exists(filename):
        return None

    if not filename.suffix == ".csv":
        return None

    with open(filename, "r") as f:
        lines = f.readlines()

    if not lines:
        return None

    headings = lines[0].strip().split(",")

    if headings == _HEADINGS:
        u_index, v_index = 2, 3
    elif headings == _HEADINGS_LEGACY:
        u_index, v_index = 1, 2
    else:
        return None

    leds = []

    for i in range(1, len(lines)):

        line = lines[i].strip().split(",")

        try:
            index = int(line[0])
            u = float(line[u_index])
            v = float(line[v_index])
        except (IndexError, ValueError):
            continue

        leds.append(LED2D(index, view_id, Point2D(u, v)))

    return leds


def get_all_2d_led_maps(directory: Path) -> list[LED2D]:
    points = []

    for view_id, filename in enumerate(sorted(os.listdir(directory))):
        full_path = Path(directory, filename)

        detections = load_detections(
            full_path, view_id
        )  # this is wrong < WHY DID I WRITE THIS???? IS IT NOT???

        if detections is not None:
            points.extend(detections)

    return points


def write_2d_leds_to_file(
    leds: list[LED2D],
    filename: Path,
    *,
    min_channel: int = 1,
    channels_per_fixture: int = 1,
):

    lines = ["index,dmx,u,v"]

    for led in sorted(leds, key=lambda led_t: led_t.led_id):
        dmx = _dmx_channel_for_led(
            led.led_id,
            min_channel=min_channel,
            channels_per_fixture=channels_per_fixture,
        )
        lines.append(
            f"{led.led_id},{dmx},{led.point.u():f},{led.point.v():f}"
        )

    with open(filename, "w") as f:
        f.write("\n".join(lines))


def list_2d_map_csv_files(directory: Path) -> list[Path]:
    """Return valid 2D map CSVs in *directory*, newest first."""
    if not directory.is_dir():
        return []
    paths = []
    for path in directory.glob("*.csv"):
        if load_detections(path, 0) is not None:
            paths.append(path)
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def map_capture_image_path(csv_path: Path) -> Path:
    """Companion camera frame for a 2D map CSV (same stem, .png)."""
    return csv_path.with_suffix(".png")


def map_annotated_image_path(csv_path: Path) -> Path:
    """Camera frame with crosshairs and DMX labels (stem + ``_map.png``)."""
    return csv_path.with_name(f"{csv_path.stem}_map.png")


def map_scan_meta_path(csv_path: Path) -> Path:
    return csv_path.with_suffix(".meta.json")


def save_map_capture_image(csv_path: Path, image) -> Path | None:
    """Save BGR camera frame next to the CSV. Returns path or None on failure."""
    import cv2

    if image is None or getattr(image, "size", 0) == 0:
        return None
    path = map_capture_image_path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        return None
    return path


def save_map_annotated_image(
    csv_path: Path,
    image,
    leds: list[LED2D],
    *,
    min_channel: int = 1,
    channels_per_fixture: int = 1,
) -> Path | None:
    """Save capture with LED crosshairs and DMX channel labels."""
    import cv2

    from marimapper.detection_map_viz import draw_led_map_with_dmx

    if image is None or getattr(image, "size", 0) == 0 or not leds:
        return None
    annotated = draw_led_map_with_dmx(
        image,
        leds,
        min_channel=min_channel,
        channels_per_fixture=channels_per_fixture,
    )
    path = map_annotated_image_path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), annotated):
        return None
    return path


def load_map_capture_image(csv_path: Path):
    """Load companion capture for a map CSV, or None if missing."""
    import cv2

    path = map_capture_image_path(csv_path)
    if not path.is_file():
        return None
    image = cv2.imread(str(path))
    if image is None or image.size == 0:
        return None
    return image


def save_map_scan_meta(
    csv_path: Path,
    scan_total: int,
    *,
    min_channel: int = 1,
    channels_per_fixture: int = 1,
) -> None:
    path = map_scan_meta_path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "scan_total": scan_total,
                "min_channel": min_channel,
                "channels_per_fixture": channels_per_fixture,
            }
        )
    )


def load_map_scan_meta(csv_path: Path) -> dict:
    path = map_scan_meta_path(csv_path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def load_map_scan_total(csv_path: Path, default: int) -> int:
    data = load_map_scan_meta(csv_path)
    try:
        return int(data["scan_total"])
    except (KeyError, TypeError, ValueError):
        return default


def load_map_dmx_settings(csv_path: Path) -> tuple[int, int]:
    """Return ``(min_channel, channels_per_fixture)`` from scan meta."""
    data = load_map_scan_meta(csv_path)
    try:
        min_channel = int(data.get("min_channel", 1))
        channels_per_fixture = int(data.get("channels_per_fixture", 1))
    except (TypeError, ValueError):
        return 1, 1
    return min_channel, channels_per_fixture


def write_3d_leds_to_file(leds: list[LED3D], filename: Path):

    lines = ["index,x,y,z,xn,yn,zn,error"]

    for led in sorted(leds, key=lambda led_t: led_t.led_id):
        lines.append(
            f"{led.led_id},"
            f"{led.point.position[0]:f},"
            f"{led.point.position[1]:f},"
            f"{led.point.position[2]:f},"
            f"{led.point.normal[0]:f},"
            f"{led.point.normal[1]:f},"
            f"{led.point.normal[2]:f},"
            f"{led.point.error:f}"
        )

    with open(filename, "w") as f:
        f.write("\n".join(lines))
