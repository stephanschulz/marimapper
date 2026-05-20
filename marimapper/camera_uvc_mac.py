"""macOS UVC camera control via IOKit (uvc-util / same path as ofxUVC)."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

UVC_UTIL_REPO = "https://github.com/jtfrey/uvc-util.git"
LOGITECH_VENDOR = 0x046D
BRIO_PRODUCT = 0x085E

_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_BIN = _PACKAGE_DIR / "bin" / "uvc-util"
_CACHE_BIN = Path.home() / ".cache" / "marimapper" / "uvc-util" / "uvc-util"


def _uvc_util_candidates() -> list[Path]:
    paths = [
        _PROJECT_BIN,
        _CACHE_BIN,
        Path("/opt/homebrew/bin/uvc-util"),
        Path("/usr/local/bin/uvc-util"),
    ]
    which = shutil.which("uvc-util")
    if which:
        paths.insert(0, Path(which))
    return paths


def find_uvc_util() -> Path | None:
    for path in _uvc_util_candidates():
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def ensure_uvc_util() -> Path:
    """Return path to uvc-util, building into ~/.cache/marimapper if needed."""
    found = find_uvc_util()
    if found is not None:
        return found

    if sys.platform != "darwin":
        raise FileNotFoundError("UVC control is only supported on macOS")

    script = _PACKAGE_DIR.parent / "scripts" / "build_uvc_util.sh"
    if script.is_file():
        subprocess.run(["sh", str(script)], check=True, timeout=120)
    else:
        cache_root = _CACHE_BIN.parent
        src = cache_root / "src"
        if not (src / ".git").is_dir():
            cache_root.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", "--depth", "1", UVC_UTIL_REPO, str(src)],
                check=True,
                timeout=120,
            )
        subprocess.run(
            [
                "gcc",
                "-o",
                str(_CACHE_BIN),
                "-framework",
                "IOKit",
                "-framework",
                "Foundation",
                "uvc-util.m",
                "UVCController.m",
                "UVCType.m",
                "UVCValue.m",
            ],
            cwd=str(src / "src"),
            check=True,
            timeout=120,
        )

    found = find_uvc_util()
    if found is None:
        raise FileNotFoundError(
            "Failed to build uvc-util. Install Xcode command-line tools and run: "
            "scripts/build_uvc_util.sh"
        )
    return found


def _run_uvc(args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    uvc = ensure_uvc_util()
    return subprocess.run(
        [str(uvc), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def list_uvc_devices() -> str:
    result = _run_uvc(["--list-devices"])
    return result.stdout + result.stderr


def _vendor_product_from_opencv_index(device_index: int) -> tuple[int, int] | None:
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeMuxed, AVMediaTypeVideo
    except ImportError:
        return None

    video = list(AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo))
    muxed = list(AVCaptureDevice.devicesWithMediaType_(AVMediaTypeMuxed))
    devices = sorted(video + muxed, key=lambda dev: str(dev.uniqueID()))
    if device_index < 0 or device_index >= len(devices):
        return None

    dev = devices[device_index]
    model = str(dev.modelID())
    match = re.search(r"VendorID_(\d+)\s+ProductID_(\d+)", model)
    if match:
        return int(match.group(1)), int(match.group(2))

    name = str(dev.localizedName()).lower()
    listing = list_uvc_devices()
    for line in listing.splitlines():
        if name.split()[0] in line.lower() or any(
            part in line.lower() for part in name.split() if len(part) > 3
        ):
            vid_match = re.search(r"0x([0-9a-fA-F]+):0x([0-9a-fA-F]+)", line)
            if vid_match:
                return int(vid_match.group(1), 16), int(vid_match.group(2), 16)
    return None


def _select_args(
    device_index: int | None,
    vendor_hex: str | None,
    product_hex: str | None,
    name_contains: str | None,
) -> list[str]:
    if device_index is not None:
        ids = _vendor_product_from_opencv_index(device_index)
        if ids is not None:
            return [
                "--select-by-vendor-and-product-id",
                f"0x{ids[0]:04x}:0x{ids[1]:04x}",
            ]

    if vendor_hex and product_hex:
        return ["--select-by-vendor-and-product-id", f"{vendor_hex}:{product_hex}"]

    if name_contains:
        listing = list_uvc_devices()
        for line in listing.splitlines():
            if name_contains.lower() in line.lower():
                match = re.search(r"0x([0-9a-fA-F]+):0x([0-9a-fA-F]+)", line)
                if match:
                    return [
                        "--select-by-vendor-and-product-id",
                        f"0x{match.group(1)}:0x{match.group(2)}",
                    ]
    return ["--select-by-vendor-and-product-id", "0x046d:0x085e"]


def slider_to_uvc_exposure_fraction(exposure: int) -> float:
    """Map marimapper exposure -13..0 to uvc-util fractional exposure-time-abs."""
    exposure = max(-13, min(0, int(exposure)))
    return (exposure + 13) / 13.0


def apply_uvc_exposure(
    exposure: int,
    *,
    device_index: int | None = None,
    vendor_hex: str | None = None,
    product_hex: str | None = None,
    name_contains: str | None = None,
    manual: bool = True,
) -> tuple[bool, str]:
    """
    Set hardware exposure through uvc-util (IOKit UVC), like ofxUVC.

    Returns (success, status message).
    """
    try:
        select = _select_args(device_index, vendor_hex, product_hex, name_contains)
        frac = slider_to_uvc_exposure_fraction(exposure)
        args: list[str] = []
        args.extend(select)

        if manual and exposure < 0:
            # Manual exposure (UVC auto-exposure-mode bitmap: 1 = manual)
            args.extend(["--set", "auto-exposure-mode=1"])
            args.extend(["--set", f"exposure-time-abs={frac:.4f}"])
            mode = "manual"
        elif not manual or exposure >= 0:
            # Auto exposure (BRIO default mode 8)
            args.extend(["--set", "auto-exposure-mode=8"])
            mode = "auto"
        else:
            args.extend(["--set", "auto-exposure-mode=1"])
            args.extend(["--set", f"exposure-time-abs={frac:.4f}"])
            mode = "manual"

        result = _run_uvc(args)
    except (OSError, subprocess.SubprocessError, FileNotFoundError) as error:
        return False, f"UVC setup failed: {error}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, f"uvc-util: {detail or result.returncode}"

    if mode == "auto":
        return True, "UVC auto exposure (IOKit)"
    return True, f"UVC manual exposure (IOKit) fraction={frac:.3f}"
