"""Background camera + DMX detection for the PySide6 GUI (no OpenCV windows)."""

from __future__ import annotations

import time

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

from marimapper.camera import Camera
from marimapper.detector import (
    draw_led_detections,
    find_led_in_image,
    set_cam_dark,
    set_cam_default,
    set_cam_preview,
)
from marimapper.led_background import LedBackgroundSubtractor
from marimapper.detection_preview import build_threshold_view
from marimapper.detection_roi import DetectionRoi
from marimapper.dmx.detection_backend import DmxDetectionBackend
from marimapper.led import LED2D
from marimapper.timeout_controller import TimeoutController

# Downscale before Qt to keep the UI responsive at 1080p.
_PREVIEW_MAX_WIDTH = 960
_PREVIEW_FRAME_MS = 20  # ~50 Hz cap (camera may deliver slower)


def _resize_for_display(frame, max_width: int = _PREVIEW_MAX_WIDTH):
    if frame is None or frame.size == 0:
        return frame
    height, width = frame.shape[:2]
    if width <= max_width:
        return frame
    scale = max_width / width
    new_size = (max_width, max(1, int(height * scale)))
    return cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)


def _configure_preview_resolution(cam: Camera) -> None:
    """Ask for a smaller capture size when the driver supports it."""
    target_w, target_h = 1280, 720
    current_w = int(cam.device.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    current_h = int(cam.device.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if current_w == target_w and current_h == target_h:
        return
    cam.device.set(cv2.CAP_PROP_FRAME_WIDTH, target_w)
    cam.device.set(cv2.CAP_PROP_FRAME_HEIGHT, target_h)


def _emit_frame_pair(
    frame_callback,
    image,
    point,
    threshold: int,
    roi: DetectionRoi | None,
    use_frame_diff: bool,
    subtractor: LedBackgroundSubtractor | None = None,
) -> None:
    camera_view = draw_led_detections(image, point)
    threshold_view = build_threshold_view(
        image,
        threshold,
        roi=roi,
        use_frame_diff=use_frame_diff,
        subtractor=subtractor,
    )
    threshold_view = draw_led_detections(threshold_view, point)
    frame_callback(
        _resize_for_display(camera_view),
        _resize_for_display(threshold_view),
    )


def _enable_and_find_led_no_gui(
    cam: Camera,
    led_backend,
    led_id: int,
    timeout_controller: TimeoutController,
    threshold: int,
    frame_callback,
    should_stop,
    use_frame_diff: bool = True,
    roi: DetectionRoi | None = None,
) -> tuple[LED2D | None, np.ndarray | None]:
    """LED detect loop; background subtraction when use_frame_diff is True."""

    darkness_timeout_seconds = 3.0
    view_id = 0
    subtractor = (
        LedBackgroundSubtractor(threshold=threshold, roi=roi)
        if use_frame_diff
        else None
    )

    start = time.time()
    while True:
        if should_stop():
            return None, None
        image = cam.read()
        if subtractor is not None:
            subtractor.update(image)
            point = subtractor.find_led(image)
        else:
            point = find_led_in_image(image, threshold, roi=roi)
        _emit_frame_pair(
            frame_callback, image, point, threshold, roi, use_frame_diff, subtractor
        )
        if point is None:
            break
        if time.time() - start > darkness_timeout_seconds:
            return None, None

    response_time_start = time.time()
    led_backend.set_led(led_id, True)

    point = None
    detection_frame = None
    while point is None and time.time() < response_time_start + timeout_controller.timeout:
        if should_stop():
            led_backend.set_led(led_id, False)
            return None, None
        image = cam.read()
        if subtractor is not None:
            point = subtractor.find_led(image)
        else:
            point = find_led_in_image(image, threshold, roi=roi)
        if point is not None:
            detection_frame = image.copy()
        _emit_frame_pair(
            frame_callback, image, point, threshold, roi, use_frame_diff, subtractor
        )

    led_backend.set_led(led_id, False)

    if point is None:
        return None, None

    detected_point = point
    timeout_controller.add_response_time(time.time() - response_time_start)

    start = time.time()
    while True:
        if should_stop():
            return None, None
        image = cam.read()
        if subtractor is not None:
            subtractor.update(image)
            point = subtractor.find_led(image)
        else:
            point = find_led_in_image(image, threshold, roi=roi)
        _emit_frame_pair(
            frame_callback, image, point, threshold, roi, use_frame_diff, subtractor
        )
        if point is None:
            break
        if time.time() - start > darkness_timeout_seconds:
            led_backend.set_led(led_id, False)
            break

    return LED2D(led_id, view_id, detected_point), detection_frame


class SharedDetectionCameraWorker(QThread):
    """
    One camera connection for preview, Test ID, and scan.

    macOS allows only one client per camera; stopping preview to test in a second
    thread left a black/frozen pane. This worker keeps a single OpenCV capture open
    and switches between preview (auto exposure) and detection (dark exposure).
    """

    frame_ready = Signal(object, object)
    status_message = Signal(str)
    error = Signal(str)
    test_finished = Signal(object)
    scan_progress = Signal(int, int, object)
    scan_finished = Signal(int, int)

    def __init__(self):
        super().__init__()
        self._quit = False
        self._stop_current = False
        self._active_mode: str | None = None
        self._device = 0
        self._exposure = -10
        self._threshold = 128
        self._resume_preview_after = False
        self._test_backend: DmxDetectionBackend | None = None
        self._test_led_id = 0
        self._scan_backend: DmxDetectionBackend | None = None
        self._scan_start = 0
        self._scan_end = 0
        self._reconfigure_exposure = True
        self._use_frame_diff = True
        self._roi = DetectionRoi()
        self._preview_subtractor: LedBackgroundSubtractor | None = None
        self.last_scan_results: list[LED2D] = []
        self.last_scan_reference_frame: np.ndarray | None = None

    def set_roi(self, roi: DetectionRoi) -> None:
        self._roi = DetectionRoi(points=list(roi.points))
        if self._preview_subtractor is not None:
            self._preview_subtractor.roi = self._roi

    def roi(self) -> DetectionRoi:
        return self._roi

    def update_threshold(self, threshold: int) -> None:
        self._threshold = threshold
        if self._preview_subtractor is not None:
            self._preview_subtractor.threshold = threshold

    def request_quit(self) -> None:
        self._quit = True
        self._stop_current = True
        self._active_mode = None

    def stop_current(self) -> None:
        """Abort preview / test / scan but keep the thread alive."""
        self._stop_current = True
        self._active_mode = None

    def is_scan_active(self) -> bool:
        return self._active_mode == "scan"

    def start_preview(self, device: int, exposure: int, threshold: int) -> None:
        self._device = device
        self._exposure = exposure
        self._threshold = threshold
        self._stop_current = False
        self._active_mode = "preview"
        self._reconfigure_exposure = True

    def update_exposure(self, exposure: int) -> None:
        self._exposure = exposure
        self._reconfigure_exposure = True

    def set_use_frame_diff(self, enabled: bool) -> None:
        self._use_frame_diff = enabled
        self._preview_subtractor = None

    def _preview_point_and_subtractor(self, image):
        if self._use_frame_diff:
            if self._preview_subtractor is None:
                self._preview_subtractor = LedBackgroundSubtractor(
                    threshold=self._threshold, roi=self._roi
                )
            self._preview_subtractor.threshold = self._threshold
            self._preview_subtractor.roi = self._roi
            self._preview_subtractor.update(image)
            return self._preview_subtractor.find_led(image), self._preview_subtractor
        return find_led_in_image(image, self._threshold, roi=self._roi), None

    def start_test(
        self,
        backend: DmxDetectionBackend,
        device: int,
        exposure: int,
        threshold: int,
        led_id: int,
        resume_preview: bool,
    ) -> None:
        self._test_backend = backend
        self._device = device
        self._exposure = exposure
        self._threshold = threshold
        self._test_led_id = led_id
        self._resume_preview_after = resume_preview
        self._stop_current = False
        self._active_mode = "test"

    def start_scan(
        self,
        backend: DmxDetectionBackend,
        device: int,
        exposure: int,
        threshold: int,
        led_start: int,
        led_end: int,
        resume_preview: bool = True,
    ) -> None:
        self._scan_backend = backend
        self._device = device
        self._exposure = exposure
        self._threshold = threshold
        self._scan_start = led_start
        self._scan_end = led_end
        self._resume_preview_after = resume_preview
        self._stop_current = False
        self._active_mode = "scan"

    def _release_camera(self, cam: Camera, *, restore_defaults: bool = False) -> None:
        # The reset+eat in set_cam_default reads ~30 frames; that is needlessly
        # slow when we're switching cameras (the device handle is about to go
        # away anyway). Only restore defaults on full shutdown.
        if restore_defaults:
            try:
                set_cam_default(cam)
            except Exception:
                pass
        try:
            cam.device.release()
        except Exception:
            pass

    def _open_camera(self, device: int) -> Camera:
        try:
            cam = Camera(device)
        except RuntimeError:
            # macOS handoff: previous capture may not have released yet.
            self.msleep(200)
            try:
                cam = Camera(device)
            except RuntimeError as error:
                raise RuntimeError(
                    f"Camera {device} busy or unavailable — close other apps using it."
                ) from error
        _configure_preview_resolution(cam)
        return cam

    def run(self) -> None:
        cam: Camera | None = None
        opened_device: int | None = None
        preview_configured = False
        dark_configured = False

        while not self._quit:
            mode = self._active_mode
            if mode is None:
                if cam is not None:
                    self._release_camera(cam)
                    cam = None
                    opened_device = None
                    preview_configured = False
                    dark_configured = False
                    self._preview_subtractor = None
                self.msleep(25)
                continue

            device = self._device
            try:
                if cam is None or opened_device != device:
                    if cam is not None:
                        self._release_camera(cam)
                    cam = self._open_camera(device)
                    opened_device = device
                    preview_configured = False
                    dark_configured = False

                if mode == "preview":
                    if not preview_configured or self._reconfigure_exposure:
                        peak = set_cam_preview(cam, self._exposure)
                        preview_configured = True
                        dark_configured = False
                        self._reconfigure_exposure = False
                        status = cam.exposure_status or "Live preview."
                        if peak < 5.0:
                            self.status_message.emit(
                                f"{status} — image is black; close other apps using this camera."
                            )
                        else:
                            self.status_message.emit(status)
                    if self._stop_current or self._active_mode != "preview":
                        continue
                    image = cam.read()
                    point, subtractor = self._preview_point_and_subtractor(image)
                    _emit_frame_pair(
                        self.frame_ready.emit,
                        image,
                        point,
                        self._threshold,
                        self._roi,
                        self._use_frame_diff,
                        subtractor,
                    )
                    self.msleep(_PREVIEW_FRAME_MS)

                elif mode == "test":
                    backend = self._test_backend
                    if backend is None:
                        self._active_mode = None
                        continue
                    if not dark_configured or self._reconfigure_exposure:
                        set_cam_dark(cam, self._exposure)
                        dark_configured = True
                        preview_configured = False
                        self._reconfigure_exposure = False
                        self.status_message.emit(
                            f"{cam.exposure_status} — detection + DMX on this ID "
                            "(scene stays dark until the LED flashes)."
                        )
                    timeout = TimeoutController()
                    result, _detection_frame = _enable_and_find_led_no_gui(
                        cam,
                        backend,
                        self._test_led_id,
                        timeout,
                        self._threshold,
                        self.frame_ready.emit,
                        lambda: self._stop_current or self._active_mode != "test",
                        use_frame_diff=self._use_frame_diff,
                        roi=self._roi,
                    )
                    try:
                        backend.all_off()
                    except Exception:
                        pass
                    self.test_finished.emit(result)
                    if self._resume_preview_after and not self._quit:
                        self._active_mode = "preview"
                    else:
                        self._active_mode = None

                elif mode == "scan":
                    backend = self._scan_backend
                    if backend is None:
                        self._active_mode = None
                        continue
                    if not dark_configured or self._reconfigure_exposure:
                        set_cam_dark(cam, self._exposure)
                        dark_configured = True
                        preview_configured = False
                        self._reconfigure_exposure = False
                        self.status_message.emit(
                            f"Scan: {cam.exposure_status} — stepping DMX IDs…"
                        )
                    total = self._scan_end - self._scan_start
                    detected = 0
                    scan_results: list[LED2D] = []
                    reference_frame = None
                    try:
                        backend.all_off()
                        for led_id in range(self._scan_start, self._scan_end):
                            if (
                                self._stop_current
                                or self._quit
                                or self._active_mode != "scan"
                            ):
                                break
                            timeout = TimeoutController()
                            led_result, detection_frame = _enable_and_find_led_no_gui(
                                cam,
                                backend,
                                led_id,
                                timeout,
                                self._threshold,
                                self.frame_ready.emit,
                                lambda: self._stop_current
                                or self._active_mode != "scan",
                                use_frame_diff=self._use_frame_diff,
                                roi=self._roi,
                            )
                            if led_result is not None and led_result.point is not None:
                                detected += 1
                                scan_results.append(led_result)
                                if detection_frame is not None:
                                    reference_frame = detection_frame
                            self.scan_progress.emit(
                                led_id - self._scan_start, total, led_result
                            )
                        if reference_frame is None:
                            frame = cam.read()
                            if frame is not None and frame.size > 0:
                                reference_frame = frame.copy()
                        self.last_scan_results = list(scan_results)
                        self.last_scan_reference_frame = reference_frame
                        self.scan_finished.emit(detected, total)
                    finally:
                        try:
                            backend.all_off()
                        except Exception:
                            pass
                    if self._resume_preview_after and not self._quit:
                        self._active_mode = "preview"
                    else:
                        self._active_mode = None

            except Exception as error:
                self.error.emit(str(error))
                self._active_mode = None
            finally:
                if self._active_mode is None and cam is not None and not self._quit:
                    pass  # release on next idle iteration

        if cam is not None:
            self._release_camera(cam, restore_defaults=True)


# Backwards-compatible aliases (same module, single implementation).
CameraPreviewWorker = SharedDetectionCameraWorker
TestLedWorker = SharedDetectionCameraWorker
DetectionScanWorker = SharedDetectionCameraWorker
