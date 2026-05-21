import tempfile
from pathlib import Path
from marimapper.file_tools import load_detections, get_all_2d_led_maps
from marimapper.led import get_led


def test_partially_valid_data():
    temp_led_map_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    temp_led_map_file.write(
        b"""index,u,v
0,0.379490,0.407710
2,0,0
2.2,0,0
bananas,apples,grapes
"""
    )
    temp_led_map_file.close()

    led_map = load_detections(Path(temp_led_map_file.name), 0)

    assert led_map is not None

    assert len(led_map) == 2

    assert get_led(led_map, 0).point.position[0] == 0.379490
    assert get_led(led_map, 0).point.position[1] == 0.407710
    assert get_led(led_map, 2).point.position[0] == 0
    assert get_led(led_map, 2).point.position[1] == 0


def test_missing_headers():
    temp_led_map_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    temp_led_map_file.write(
        b"""index,v,u
0,0.379490,0.407710"""
    )

    temp_led_map_file.close()

    led_map = load_detections(Path(temp_led_map_file.name), 0)

    assert led_map is None, "led map successfully loaded without correct headers"


def test_invalid_path():

    led_map = load_detections(Path("doesnt-exist-i-hope"), 0)
    assert led_map is None, "led map successfully loaded from invalid file"


def test_get_all_maps():

    directory = tempfile.TemporaryDirectory()

    temp_led_map_file = tempfile.NamedTemporaryFile(
        delete=False, suffix=".csv", dir=directory.name
    )
    temp_led_map_file.write(
        b"""index,u,v
0,0.379490,0.407710
"""
    )
    temp_led_map_file.close()

    temp_led_map_file_invalid = tempfile.NamedTemporaryFile(
        delete=False, suffix=".html", dir=directory.name
    )
    temp_led_map_file_invalid.write(
        b"""index,u,v
0,0.379490,0.407710
"""
    )
    temp_led_map_file_invalid.close()

    all_maps = get_all_2d_led_maps(Path(directory.name))

    assert len(all_maps) == 1, "expected 1 map"

    directory.cleanup()


def test_list_2d_map_csv_files():
    from marimapper.file_tools import list_2d_map_csv_files

    directory = tempfile.TemporaryDirectory()
    valid = Path(directory.name) / "led_map_2d_0000.csv"
    valid.write_text("index,u,v\n0,0.1,0.2\n")
    invalid = Path(directory.name) / "notes.txt"
    invalid.write_text("not a map")

    listed = list_2d_map_csv_files(Path(directory.name))
    assert listed == [valid]

    directory.cleanup()


def test_write_2d_leds_includes_dmx():
    from marimapper.file_tools import write_2d_leds_to_file
    from marimapper.led import LED2D, Point2D

    directory = tempfile.TemporaryDirectory()
    csv_path = Path(directory.name) / "led_map_2d_test.csv"
    leds = [LED2D(2, 0, Point2D(0.1, 0.2))]

    write_2d_leds_to_file(
        leds, csv_path, min_channel=10, channels_per_fixture=3
    )
    text = csv_path.read_text()
    assert text.splitlines() == ["index,dmx,u,v", "2,16,0.100000,0.200000"]

    loaded = load_detections(csv_path, 0)
    assert loaded is not None
    assert len(loaded) == 1
    assert loaded[0].led_id == 2

    directory.cleanup()


def test_fill_missing_leds_creates_placeholders():
    from marimapper.file_tools import fill_missing_leds, is_led_missing
    from marimapper.led import LED2D, Point2D

    leds = [LED2D(0, 0, Point2D(0.1, 0.2)), LED2D(2, 0, Point2D(0.4, 0.5))]
    full = fill_missing_leds(leds, total=4)

    assert [led.led_id for led in full] == [0, 1, 2, 3]
    assert not is_led_missing(full[0])
    assert is_led_missing(full[1])
    assert full[1].point.u() == -1.0 and full[1].point.v() == -1.0
    assert not is_led_missing(full[2])
    assert is_led_missing(full[3])


def test_missing_led_csv_roundtrip(tmp_path):
    from marimapper.file_tools import (
        fill_missing_leds,
        is_led_missing,
        write_2d_leds_to_file,
    )
    from marimapper.led import LED2D, Point2D

    csv_path = tmp_path / "led_map_2d_missing.csv"
    full = fill_missing_leds(
        [LED2D(1, 0, Point2D(0.3, 0.4))], total=3
    )
    write_2d_leds_to_file(full, csv_path, min_channel=5, channels_per_fixture=2)

    loaded = load_detections(csv_path, 0)
    assert loaded is not None
    assert [led.led_id for led in loaded] == [0, 1, 2]
    assert is_led_missing(loaded[0])
    assert not is_led_missing(loaded[1])
    assert loaded[1].point.u() == 0.3
    assert is_led_missing(loaded[2])

    # DMX channel column is correct for the missing rows too.
    dmx_values = [line.split(",")[1] for line in csv_path.read_text().splitlines()[1:]]
    assert dmx_values == ["5", "7", "9"]


def test_map_capture_image_roundtrip():
    import cv2
    import numpy as np

    from marimapper.file_tools import (
        load_map_capture_image,
        load_map_dmx_settings,
        load_map_scan_total,
        map_annotated_image_path,
        map_capture_image_path,
        save_map_annotated_image,
        save_map_capture_image,
        save_map_scan_meta,
    )
    from marimapper.led import LED2D, Point2D

    directory = tempfile.TemporaryDirectory()
    csv_path = Path(directory.name) / "led_map_2d_test.csv"
    csv_path.write_text("index,u,v\n0,0.1,0.2\n")
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    frame[20:28, 30:38] = (0, 255, 0)
    leds = [LED2D(0, 0, Point2D(0.1, 0.2))]

    saved = save_map_capture_image(csv_path, frame)
    assert saved == map_capture_image_path(csv_path)
    assert saved.is_file()

    annotated = save_map_annotated_image(
        csv_path, frame, leds, min_channel=5, channels_per_fixture=2
    )
    assert annotated == map_annotated_image_path(csv_path)
    assert annotated.is_file()

    loaded = load_map_capture_image(csv_path)
    assert loaded is not None
    assert loaded.shape == frame.shape
    assert loaded[24, 34].tolist() == [0, 255, 0]

    save_map_scan_meta(csv_path, 42, min_channel=5, channels_per_fixture=2)
    assert load_map_scan_total(csv_path, 0) == 42
    assert load_map_dmx_settings(csv_path) == (5, 2)

    directory.cleanup()
