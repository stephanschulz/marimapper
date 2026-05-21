import sys
from types import SimpleNamespace
from unittest.mock import patch

from marimapper.camera_devices import (
    _camera_name_map,
    _ffmpeg_avfoundation_video_names,
    _label_for_index,
    _macos_opencv_device_names,
    list_cameras,
    probe_single_camera,
)


def test_label_for_index_with_name_map():
    name_map = {0: "NDI Virtual Camera", 3: "Logitech BRIO"}
    assert _label_for_index(3, name_map, 100.0) == "[3] Logitech BRIO"
    assert _label_for_index(3, name_map, 0.0) == "[3] Logitech BRIO — no image (busy or lens covered?)"
    assert _label_for_index(9, name_map, 50.0) == "[9] Camera 9"


def test_macos_opencv_device_names_sorted_by_unique_id(monkeypatch):
    class FakeDevice:
        def __init__(self, name, uid):
            self._name = name
            self._uid = uid

        def localizedName(self):
            return self._name

        def uniqueID(self):
            return self._uid

    # Unsorted input; OpenCV order is by uniqueID string compare.
    video_devices = [
        FakeDevice("Logitech BRIO", "0x240000046d085e"),
        FakeDevice("Kurokesu C1 MICRO", "0x13400016d00ed2"),
    ]

    def devices_with_media(media_type):
        if media_type == "video":
            return video_devices
        return []

    monkeypatch.setitem(
        sys.modules,
        "AVFoundation",
        SimpleNamespace(
            AVCaptureDevice=SimpleNamespace(
                devicesWithMediaType_=devices_with_media
            ),
            AVMediaTypeVideo="video",
            AVMediaTypeMuxed="muxed",
        ),
    )
    assert _macos_opencv_device_names() == {
        0: "Kurokesu C1 MICRO",
        1: "Logitech BRIO",
    }


def test_camera_name_map_prefers_avfoundation(monkeypatch):
    monkeypatch.setattr(
        "marimapper.camera_devices._macos_opencv_device_names",
        lambda: {0: "Kurokesu C1 MICRO"},
    )
    monkeypatch.setattr(
        "marimapper.camera_devices._ffmpeg_avfoundation_video_names",
        lambda: {0: "OBSBOT Virtual Camera"},
    )
    monkeypatch.setattr("marimapper.camera_devices.sys.platform", "darwin")
    assert _camera_name_map() == {0: "Kurokesu C1 MICRO"}


def test_ffmpeg_parse_video_devices():
    stderr = """
[AVFoundation indev @ 0x0] AVFoundation video devices:
[AVFoundation indev @ 0x0] [0] NDI Virtual Camera
[AVFoundation indev @ 0x0] [3] Logitech BRIO
[AVFoundation indev @ 0x0] AVFoundation audio devices:
[AVFoundation indev @ 0x0] [0] MacBook Pro Microphone
"""
    with patch("marimapper.camera_devices.shutil.which", return_value="/usr/bin/ffmpeg"):
        with patch("marimapper.camera_devices.subprocess.run") as run:
            run.return_value.stderr = stderr
            run.return_value.stdout = ""
            names = _ffmpeg_avfoundation_video_names()
    assert names == {0: "NDI Virtual Camera", 3: "Logitech BRIO"}


def test_probe_single_camera_only_probes_target(monkeypatch):
    """The fast path must not enumerate every index."""
    probed: list[int] = []

    def fake_probe(index, backends, warmup_reads=5):
        probed.append(index)
        return (True, 120.0) if index == 4 else (False, 0.0)

    monkeypatch.setattr(
        "marimapper.camera_devices._probe_opencv_index", fake_probe
    )
    monkeypatch.setattr(
        "marimapper.camera_devices._camera_name_map",
        lambda: {4: "Logitech BRIO"},
    )

    result = probe_single_camera(4)
    assert result == (4, "[4] Logitech BRIO")
    assert probed == [4]


def test_probe_single_camera_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr(
        "marimapper.camera_devices._probe_opencv_index",
        lambda index, backends, warmup_reads=5: (False, 0.0),
    )
    monkeypatch.setattr(
        "marimapper.camera_devices._camera_name_map", lambda: {}
    )
    assert probe_single_camera(7) is None


def test_list_cameras_no_early_stop(monkeypatch):
    def fake_probe(index, backends, warmup_reads=8):
        if index in (0, 3):
            return True, 120.0 if index == 0 else 0.0
        return False, 0.0

    monkeypatch.setattr(
        "marimapper.camera_devices._probe_opencv_index", fake_probe
    )
    monkeypatch.setattr(
        "marimapper.camera_devices._camera_name_map",
        lambda: {0: "NDI Virtual Camera", 3: "Logitech BRIO"},
    )
    cameras = list_cameras(max_probe=6)
    assert cameras == [
        (0, "[0] NDI Virtual Camera"),
        (3, "[3] Logitech BRIO — no image (busy or lens covered?)"),
    ]
