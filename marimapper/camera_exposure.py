"""Camera exposure: hardware where possible, software fallback on macOS."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from marimapper.camera import Camera

logger = logging.getLogger(__name__)

# OpenCV on macOS AVFoundation only implements size/FPS in setProperty — not exposure.
_DARWIN_OPENCV_EXPOSURE_SUPPORTED = False if sys.platform == "darwin" else True


def slider_to_gain(exposure: int) -> float:
    """Map GUI exposure -13 (darkest) .. 0 (brightest) to a linear brightness scale."""
    exposure = max(-13, min(0, int(exposure)))
    return 2.0 ** float(exposure)


def apply_software_gain(frame: np.ndarray, gain: float) -> np.ndarray:
    if gain >= 0.999:
        return frame
    return np.clip(frame.astype(np.float32) * gain, 0, 255).astype(np.uint8)


def _sorted_av_capture_devices():
    try:
        from AVFoundation import (
            AVCaptureDevice,
            AVMediaTypeMuxed,
            AVMediaTypeVideo,
            AVCaptureExposureModeContinuousAutoExposure,
            AVCaptureExposureModeCustom,
            AVCaptureExposureModeLocked,
        )
        import CoreMedia
    except ImportError:
        return None, None

    video = list(AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo))
    muxed = list(AVCaptureDevice.devicesWithMediaType_(AVMediaTypeMuxed))
    devices = sorted(video + muxed, key=lambda dev: str(dev.uniqueID()))
    ctx = {
        "AVCaptureExposureModeContinuousAutoExposure": AVCaptureExposureModeContinuousAutoExposure,
        "AVCaptureExposureModeCustom": AVCaptureExposureModeCustom,
        "AVCaptureExposureModeLocked": AVCaptureExposureModeLocked,
        "CoreMedia": CoreMedia,
    }
    return devices, ctx


def _darwin_device_for_index(device_index: int):
    devices, _ctx = _sorted_av_capture_devices()
    if not devices or device_index < 0 or device_index >= len(devices):
        return None, None
    return devices[device_index], _ctx


def _darwin_try_hardware(device, exposure: int, dark: bool, ctx) -> bool:
    """Return True if AVFoundation reports manual/custom exposure is active."""
    import CoreMedia

    AVCaptureExposureModeContinuousAutoExposure = ctx[
        "AVCaptureExposureModeContinuousAutoExposure"
    ]
    AVCaptureExposureModeCustom = ctx["AVCaptureExposureModeCustom"]
    AVCaptureExposureModeLocked = ctx["AVCaptureExposureModeLocked"]

    locked = device.lockForConfiguration_(None)
    if not locked:
        return False

    try:
        if not dark and exposure >= 0:
            if device.isExposureModeSupported_(
                AVCaptureExposureModeContinuousAutoExposure
            ):
                device.setExposureMode_(AVCaptureExposureModeContinuousAutoExposure)
                return True
            return False

        if device.isExposureModeSupported_(AVCaptureExposureModeCustom):
            fmt = device.activeFormat()
            min_iso = float(fmt.minISO())
            max_iso = float(fmt.maxISO())
            min_dur = fmt.minExposureDuration()
            max_dur = fmt.maxExposureDuration()

            if max_iso > min_iso and max_dur.value > 0:
                # 0 = darkest, 1 = brightest within marimapper slider range
                t = (exposure + 13) / 13.0
                iso = min_iso + t * (max_iso - min_iso)
                dur_value = int(
                    max_dur.value + (1.0 - t) * (min_dur.value - max_dur.value)
                )
                dur_scale = max_dur.timescale or min_dur.timescale or 1_000_000
                duration = CoreMedia.CMTimeMake(dur_value, dur_scale)
                device.setExposureModeCustomWithDuration_ISO_completionHandler_(
                    duration, iso, None
                )
                return True

        if device.isExposureModeSupported_(AVCaptureExposureModeLocked):
            device.setExposureMode_(AVCaptureExposureModeLocked)
            # Locked only freezes auto level — not reliably dark on BRIO.
            return False
    except Exception as error:
        logger.debug("AVFoundation exposure failed: %s", error)
        return False
    finally:
        device.unlockForConfiguration()

    return False


def _try_opencv_exposure(cap: cv2.VideoCapture, exposure: int, dark: bool) -> bool:
    if not _DARWIN_OPENCV_EXPOSURE_SUPPORTED:
        return False

    if dark:
        manual_auto = 0.25
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, manual_auto)
        cap.set(cv2.CAP_PROP_GAIN, 0)
        return cap.set(cv2.CAP_PROP_EXPOSURE, float(exposure))

    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)
    return True


def configure_camera_exposure(
    cam: Camera, exposure: int, *, dark: bool = False
) -> tuple[str, float | None]:
    """
    Apply exposure for preview or LED detection.

    Returns (status text, software_gain multiplier or None).
    """
    exposure = max(-13, min(0, int(exposure)))
    parts: list[str] = []
    hardware = False

    if isinstance(cam.device_id, int):
        if sys.platform == "darwin":
            from marimapper.camera_uvc_mac import apply_uvc_exposure

            uvc_ok, uvc_msg = apply_uvc_exposure(
                exposure,
                device_index=cam.device_id,
                manual=dark or exposure < 0,
            )
            if uvc_ok:
                parts.append(uvc_msg)
                hardware = True
                software_gain = None
                return " — ".join(parts), software_gain
            parts.append(uvc_msg)

            device, ctx = _darwin_device_for_index(cam.device_id)
            if device is not None and ctx is not None:
                hardware = _darwin_try_hardware(device, exposure, dark, ctx)
                if hardware:
                    parts.append("hardware (AVFoundation)")
                else:
                    parts.append(
                        "macOS: OpenCV/AVFoundation does not expose UVC exposure on "
                        f"{device.localizedName()} — using software scaling"
                    )
            else:
                parts.append("macOS: software exposure (PyObjC unavailable)")

        if _try_opencv_exposure(cam.device, exposure, dark):
            parts.append("hardware (OpenCV)")
            hardware = True

    software_gain: float | None = None
    # With hardware UVC or mild exposure, avoid crushing the image when using frame diff.
    need_software = (dark or exposure < 0 or not hardware) and (
        not hardware or exposure < -4
    )
    if need_software:
        software_gain = slider_to_gain(exposure)
        if software_gain < 0.999:
            parts.append(f"software ×{software_gain:.4f}")

    if not dark and exposure >= 0 and software_gain is None:
        if sys.platform == "darwin":
            cam.device.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)
        parts.append("auto exposure")

    return " — ".join(parts) if parts else "exposure unchanged", software_gain
