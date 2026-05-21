"""Enumerate webcam indices for GUI selection."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys

import cv2

# Names we should not offer for LED detection.
_SKIP_CAMERA_KEYWORDS = ("capture screen",)


def _capture_backends() -> list[int]:
    if sys.platform == "darwin":
        return [cv2.CAP_AVFOUNDATION, cv2.CAP_ANY]
    if sys.platform == "win32":
        return [cv2.CAP_DSHOW, cv2.CAP_ANY]
    return [cv2.CAP_V4L2, cv2.CAP_ANY]


def _should_skip_camera(name: str) -> bool:
    lower = name.lower()
    return any(keyword in lower for keyword in _SKIP_CAMERA_KEYWORDS)


def _macos_opencv_device_names() -> dict[int, str]:
    """
    Map OpenCV index -> device name using the same list and order as OpenCV.

    ``cap_avfoundation_mac.mm`` collects video + muxed devices, then sorts by
    ``uniqueID`` (NSString compare) before assigning capture indices. The raw
    ``devicesWithMediaType`` order is different and causes label/preview mismatches.
    """
    try:
        from AVFoundation import (
            AVCaptureDevice,
            AVMediaTypeMuxed,
            AVMediaTypeVideo,
        )
    except ImportError:
        return {}

    video = list(AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo))
    muxed = list(AVCaptureDevice.devicesWithMediaType_(AVMediaTypeMuxed))
    devices = sorted(
        video + muxed,
        key=lambda dev: str(dev.uniqueID()),
    )
    return {i: str(dev.localizedName()) for i, dev in enumerate(devices)}


def _ffmpeg_avfoundation_video_names() -> dict[int, str]:
    """
    Fallback map from ``ffmpeg -list_devices`` (order may not match OpenCV).
    """
    if shutil.which("ffmpeg") is None:
        return {}

    try:
        result = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    names: dict[int, str] = {}
    in_video = False
    for line in result.stderr.splitlines():
        if "AVFoundation video devices" in line:
            in_video = True
            continue
        if "AVFoundation audio devices" in line:
            break
        match = re.search(r"\[(\d+)\]\s+(.+)", line)
        if in_video and match:
            names[int(match.group(1))] = match.group(2).strip()
    return names


def _macos_system_profiler_names() -> list[str]:
    """Fallback only — order may not match OpenCV indices."""
    try:
        result = subprocess.run(
            ["system_profiler", "SPCameraDataType", "-json"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        data = json.loads(result.stdout)
        items = data.get("SPCameraDataType", [])
        return [str(item.get("_name", "Camera")) for item in items]
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return []


def _camera_name_map() -> dict[int, str]:
    if sys.platform == "darwin":
        opencv_names = _macos_opencv_device_names()
        if opencv_names:
            return opencv_names
        ffmpeg_names = _ffmpeg_avfoundation_video_names()
        if ffmpeg_names:
            return ffmpeg_names
    return {}


def _label_for_index(index: int, name_map: dict[int, str], peak_brightness: float) -> str:
    base = f"[{index}] {name_map[index]}" if index in name_map else f"[{index}] Camera {index}"
    if peak_brightness < 5.0:
        return f"{base} — no image (busy or lens covered?)"
    return base


def _probe_opencv_index(
    index: int, backends: list[int], warmup_reads: int = 30
) -> tuple[bool, float]:
    """Return (captures_frames, peak_brightness)."""
    peak = 0.0
    for backend in backends:
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            cap.release()
            continue
        try:
            if sys.platform == "darwin":
                cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)
            got_frame = False
            for _ in range(warmup_reads):
                ok, frame = cap.read()
                if ok and frame is not None and getattr(frame, "size", 0) > 0:
                    got_frame = True
                    peak = max(peak, float(frame.mean()))
            if got_frame:
                return True, peak
        finally:
            cap.release()
    return False, peak


def probe_single_camera(index: int) -> tuple[int, str] | None:
    """
    Fast check for a single camera index without enumerating others.

    Used for the startup fast path so we don't scan all 16 indexes when the
    last-selected camera is still present. Uses fewer warmup reads than the
    full enumeration.
    """
    backends = _capture_backends()
    ok, peak = _probe_opencv_index(index, backends, warmup_reads=5)
    if not ok:
        return None
    name_map = _camera_name_map()
    label = _label_for_index(index, name_map, peak)
    if _should_skip_camera(label):
        return None
    return index, label


def list_cameras(max_probe: int = 16) -> list[tuple[int, str]]:
    """
    Return (device_index, label) for each camera that captures frames.

    On macOS, labels use the same AVFoundation device list as OpenCV's
    AVFoundation backend (video + muxed, sorted by ``uniqueID``). ``ffmpeg
    -list_devices`` is only a fallback when PyObjC is unavailable.
    """
    backends = _capture_backends()
    name_map = _camera_name_map()
    found: list[tuple[int, str]] = []

    for index in range(max_probe):
        ok, peak = _probe_opencv_index(index, backends)
        if not ok:
            continue
        label = _label_for_index(index, name_map, peak)
        if _should_skip_camera(label):
            continue
        found.append((index, label))

    return found


def default_camera_index(cameras: list[tuple[int, str]]) -> int:
    if not cameras:
        return 0
    prefer_keywords = ("kurokesu", "logitech", "brio", "uvc", "usb")
    skip_keywords = (
        "virtual",
        "ndi",
        "obsbot",
        "iphone",
        "phone camera",
        "facetime",
        "no image",
    )
    for index, label in cameras:
        lower = label.lower()
        if any(skip in lower for skip in skip_keywords):
            continue
        if any(key in lower for key in prefer_keywords):
            return index
    return cameras[0][0]
