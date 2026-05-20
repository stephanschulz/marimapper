"""Separate window for camera preview and LED detection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from marimapper.camera_devices import default_camera_index, list_cameras
from marimapper.detection_roi import DetectionRoi
from marimapper.dmx.detection_worker import SharedDetectionCameraWorker
from marimapper.dmx.map_results_window import MapResultsWindow
from marimapper.dmx.roi_preview import FramePreviewWidget, LabeledPreview, RoiPreviewWidget
from marimapper.led import LED2D

if TYPE_CHECKING:
    from marimapper.dmx.gui import DmxControllerWindow


class CameraDetectionWindow(QMainWindow):
    """Live camera feed + detection controls (preview stays on during test/scan)."""

    def __init__(self, controller: DmxControllerWindow):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Camera — LED detection")
        self.setMinimumSize(720, 560)

        self._camera_worker: SharedDetectionCameraWorker | None = None
        self._pending_camera: int | None = None
        self._live_view_enabled = True
        self._map_results_window: MapResultsWindow | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        preview_row = QHBoxLayout()
        self.det_preview = RoiPreviewWidget()
        self.det_preview.roi_changed.connect(self._on_roi_changed)
        self.det_threshold_preview = FramePreviewWidget()
        preview_row.addWidget(
            LabeledPreview("Live camera", self.det_preview), stretch=1
        )
        preview_row.addWidget(
            LabeledPreview("Threshold view (detection input)", self.det_threshold_preview),
            stretch=1,
        )
        layout.addLayout(preview_row, stretch=1)

        roi_row = QHBoxLayout()
        self.btn_roi_draw = QPushButton("Draw ROI")
        self.btn_roi_draw.setCheckable(True)
        self.btn_roi_draw.clicked.connect(self._toggle_roi_draw)
        roi_row.addWidget(self.btn_roi_draw)
        self.btn_roi_close = QPushButton("Close polygon")
        self.btn_roi_close.clicked.connect(self._close_roi_polygon)
        roi_row.addWidget(self.btn_roi_close)
        self.btn_roi_clear = QPushButton("Clear ROI")
        self.btn_roi_clear.clicked.connect(self._clear_roi)
        roi_row.addWidget(self.btn_roi_clear)
        layout.addLayout(roi_row)

        controls = QGroupBox("Camera & detection")
        form = QFormLayout(controls)

        cam_select_row = QHBoxLayout()
        self.det_camera_combo = QComboBox()
        self.det_camera_refresh = QPushButton("Refresh")
        self.det_camera_refresh.clicked.connect(self.refresh_cameras)
        cam_select_row.addWidget(self.det_camera_combo)
        cam_select_row.addWidget(self.det_camera_refresh)
        form.addRow("Camera:", cam_select_row)

        cam_row = QHBoxLayout()
        cam_row.addWidget(QLabel("Exposure"))
        self.det_exposure = QSpinBox()
        self.det_exposure.setRange(-13, 0)
        self.det_exposure.setValue(-10)
        self.det_exposure.setToolTip(
            "0 = auto where supported. Negative = darker (software on macOS for BRIO)."
        )
        self.det_exposure.valueChanged.connect(self._on_det_exposure_changed)
        cam_row.addWidget(self.det_exposure)
        cam_row.addWidget(QLabel("Threshold"))
        self.det_threshold = QSpinBox()
        self.det_threshold.setRange(0, 255)
        self.det_threshold.setValue(128)
        self.det_threshold.setToolTip(
            "Brightness cutoff (0–255). Higher = only brighter pixels count; "
            "lower = more sensitive. Right panel shows this threshold live."
        )
        self.det_threshold.valueChanged.connect(self._on_threshold_changed)
        cam_row.addWidget(self.det_threshold)
        form.addRow("", cam_row)

        self.det_frame_diff = QCheckBox("Frame difference (averaged background)")
        self.det_frame_diff.setChecked(True)
        self.det_frame_diff.setToolTip(
            "Learn background while LEDs are off, then detect bright flashes. "
            "Works better than a global threshold on a dark image. Preview shows the diff."
        )
        self.det_frame_diff.toggled.connect(self._on_frame_diff_toggled)
        form.addRow("", self.det_frame_diff)

        id_row = QHBoxLayout()
        self.det_current_id = QSpinBox()
        self.det_current_id.setRange(0, 9999)
        self.det_current_id.setValue(0)
        self.det_current_id.valueChanged.connect(self._on_led_index_changed)
        id_row.addWidget(self.det_current_id)
        self.btn_det_test = QPushButton("Test this ID")
        self.btn_det_test.clicked.connect(self.test_detection_id)
        id_row.addWidget(self.btn_det_test)
        form.addRow("LED index:", id_row)

        det_btn_row = QHBoxLayout()
        self.btn_det_pause = QPushButton("Pause live view")
        self.btn_det_pause.setCheckable(True)
        self.btn_det_pause.clicked.connect(self.toggle_pause_live_view)
        det_btn_row.addWidget(self.btn_det_pause)
        self.btn_det_scan = QPushButton("Run 2D detection scan")
        self.btn_det_scan.setToolTip(
            "Scan every LED from one camera angle. Opens a 2D map when done "
            "(multi-angle 3D reconstruction is not required)."
        )
        self.btn_det_scan.clicked.connect(self.toggle_detection_scan)
        det_btn_row.addWidget(self.btn_det_scan)
        self.btn_det_stop = QPushButton("Stop camera")
        self.btn_det_stop.clicked.connect(self.stop_camera)
        det_btn_row.addWidget(self.btn_det_stop)
        form.addRow("", det_btn_row)

        self.det_status = QLabel(
            "Live view starts when this window opens. Test/scan keep the feed running."
        )
        self.det_status.setWordWrap(True)
        self.det_status.setFont(QFont("Helvetica", 11))
        form.addRow("", self.det_status)

        layout.addWidget(controls)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.det_camera_combo.count() == 0:
            self.refresh_cameras()
        self._sync_led_index_range()
        self._on_led_index_changed(self.det_current_id.value())
        if self._live_view_enabled and not self.btn_det_pause.isChecked():
            self.start_live_view()

    def closeEvent(self, event) -> None:
        self.stop_camera()
        super().closeEvent(event)

    def selected_camera_index(self) -> int:
        data = self.det_camera_combo.currentData()
        if data is not None:
            return int(data)
        return 0

    def set_pending_camera(self, index: int) -> None:
        self._pending_camera = index

    def apply_settings(self, settings: dict) -> None:
        self._pending_camera = settings.get("det_camera", 0)
        self.det_exposure.setValue(settings.get("det_exposure", -10))
        self.det_threshold.setValue(settings.get("det_threshold", 128))
        self.det_frame_diff.setChecked(settings.get("det_frame_diff", True))
        self.det_current_id.setValue(settings.get("det_current_id", 0))
        self.det_preview.set_roi(DetectionRoi.from_list(settings.get("det_roi")))
        self._sync_roi_to_worker()
        if self.isVisible():
            self.refresh_cameras()

    def settings_snapshot(self) -> dict:
        return {
            "det_camera": self.selected_camera_index(),
            "det_exposure": self.det_exposure.value(),
            "det_threshold": self.det_threshold.value(),
            "det_frame_diff": self.det_frame_diff.isChecked(),
            "det_current_id": self.det_current_id.value(),
            "det_roi": self.det_preview.roi().to_list(),
        }

    def refresh_cameras(self) -> None:
        current = self.det_camera_combo.currentData()
        self.det_camera_combo.clear()
        cameras = list_cameras()
        if not cameras:
            self.det_camera_combo.addItem("No camera found", 0)
            self.det_status.setText("No camera detected — check USB and permissions.")
            return

        for index, label in cameras:
            self.det_camera_combo.addItem(label, index)

        restore = self._pending_camera if self._pending_camera is not None else current
        if restore is not None:
            idx = self.det_camera_combo.findData(restore)
            if idx >= 0:
                self.det_camera_combo.setCurrentIndex(idx)
            else:
                prefer = default_camera_index(cameras)
                idx = self.det_camera_combo.findData(prefer)
                if idx >= 0:
                    self.det_camera_combo.setCurrentIndex(idx)
        self._pending_camera = None

        if self._live_view_enabled and not self.btn_det_pause.isChecked():
            self.start_live_view()

    def show_detection_frame(self, camera_frame, threshold_frame=None) -> None:
        self.det_preview.set_frame(camera_frame)
        if threshold_frame is not None:
            self.det_threshold_preview.set_frame(threshold_frame)

    def _sync_roi_to_worker(self) -> None:
        if self._camera_worker is not None and self._camera_worker.isRunning():
            self._camera_worker.set_roi(self.det_preview.roi())

    def _on_roi_changed(self, _roi: DetectionRoi) -> None:
        self._sync_roi_to_worker()
        if self.det_preview.roi().is_valid():
            n = len(self.det_preview.roi().points)
            self.det_status.setText(f"ROI set — detection limited to {n}-point polygon.")
        elif not self.det_preview.is_drawing():
            self.det_status.setText("ROI cleared — full frame used for detection.")

    def _toggle_roi_draw(self, checked: bool) -> None:
        if checked:
            self.det_preview.start_drawing()
            self.det_status.setText(
                "ROI draw mode: click corners on the preview, then Close polygon."
            )
        else:
            self.det_preview.cancel_drawing()

    def _close_roi_polygon(self) -> None:
        if self.det_preview.close_polygon():
            self.btn_roi_draw.setChecked(False)
        else:
            self.det_status.setText("Need at least 3 points to close the ROI polygon.")

    def _clear_roi(self) -> None:
        self.btn_roi_draw.setChecked(False)
        self.det_preview.clear_roi()

    def _ensure_camera_worker(self) -> SharedDetectionCameraWorker:
        if self._camera_worker is not None and self._camera_worker.isRunning():
            return self._camera_worker
        worker = SharedDetectionCameraWorker()
        worker.set_use_frame_diff(self.det_frame_diff.isChecked())
        worker.set_roi(self.det_preview.roi())
        worker.frame_ready.connect(self.show_detection_frame)
        worker.status_message.connect(self.det_status.setText)
        worker.error.connect(self._on_detection_error)
        worker.test_finished.connect(self._on_test_finished)
        worker.scan_progress.connect(self._on_scan_progress)
        worker.scan_finished.connect(self._on_scan_finished)
        worker.start()
        self._camera_worker = worker
        return worker

    def _wants_live_feed(self) -> bool:
        return self._live_view_enabled and not self.btn_det_pause.isChecked()

    def start_live_view(self) -> None:
        if not self._wants_live_feed():
            return
        worker = self._ensure_camera_worker()
        worker.start_preview(
            self.selected_camera_index(),
            self.det_exposure.value(),
            self.det_threshold.value(),
        )

    def stop_camera(self) -> None:
        if self._camera_worker is not None:
            self._camera_worker.request_quit()
            self._camera_worker.wait(5000)
            self._camera_worker = None
        self.btn_det_pause.setChecked(False)
        self.btn_det_scan.setEnabled(True)
        self.btn_det_test.setEnabled(True)
        self.det_preview._pixmap = None
        self.det_preview.update()
        self.det_threshold_preview.set_frame(None)
        self.det_status.setText("Camera stopped.")

    def toggle_pause_live_view(self, paused: bool) -> None:
        if paused:
            if self._camera_worker is not None:
                self._camera_worker.stop_current()
            self.det_status.setText("Live view paused — test/scan still show frames.")
        else:
            self.start_live_view()

    def _on_det_exposure_changed(self, _value: int) -> None:
        if self._camera_worker is not None and self._camera_worker.isRunning():
            self._camera_worker.update_exposure(self.det_exposure.value())

    def _sync_led_index_range(self) -> None:
        try:
            total = self.controller.detection_fixture_count()
            self.det_current_id.setMaximum(max(0, total - 1))
        except Exception:
            pass

    def _on_led_index_changed(self, led_id: int) -> None:
        if (
            self._camera_worker is not None
            and self._camera_worker.isRunning()
            and self._camera_worker.is_scan_active()
        ):
            return
        try:
            dmx_ch, level = self.controller.highlight_detection_led(led_id)
            universe = self.controller.det_universe.value()
            extra = f", universe {universe}" if self.controller.device_mode == "Art-Net" else ""
            self.det_status.setText(
                f"DMX ch {dmx_ch} = {level}, all others 0 (LED index {led_id}{extra})"
            )
        except Exception as error:
            self.det_status.setText(f"DMX highlight failed: {error}")

    def _on_frame_diff_toggled(self, _checked: bool) -> None:
        if self._camera_worker is not None and self._camera_worker.isRunning():
            self._camera_worker.set_use_frame_diff(self.det_frame_diff.isChecked())

    def _on_threshold_changed(self, value: int) -> None:
        if self._camera_worker is not None and self._camera_worker.isRunning():
            self._camera_worker.update_threshold(value)

    def test_detection_id(self) -> None:
        try:
            backend = self.controller.build_detection_backend()
            config = backend.config
            led_id = self.det_current_id.value()
            if led_id < 0 or led_id >= backend.get_led_count():
                raise ValueError(
                    f"LED index {led_id} out of range 0–{backend.get_led_count() - 1}"
                )
            dmx_ch = config.min_channel + led_id * config.channels_per_fixture
            self.det_status.setText(
                f"Testing LED {led_id} → DMX ch {dmx_ch}"
                + (
                    f" (universe {config.universe})"
                    if self.controller.device_mode == "Art-Net"
                    else ""
                )
            )
            self.btn_det_test.setEnabled(False)
            worker = self._ensure_camera_worker()
            worker.start_test(
                backend,
                self.selected_camera_index(),
                self.det_exposure.value(),
                self.det_threshold.value(),
                led_id,
                resume_preview=self._wants_live_feed(),
            )
        except Exception as error:
            self._on_detection_error(str(error))

    def toggle_detection_scan(self) -> None:
        if (
            self._camera_worker is not None
            and self._camera_worker.isRunning()
            and self._camera_worker.is_scan_active()
        ):
            self._camera_worker.stop_current()
            self.btn_det_scan.setEnabled(True)
            if self._wants_live_feed():
                self.start_live_view()
            return
        try:
            backend = self.controller.build_detection_backend()
            total = backend.get_led_count()
            self._sync_led_index_range()
            worker = self._ensure_camera_worker()
            worker.start_scan(
                backend,
                self.selected_camera_index(),
                self.det_exposure.value(),
                self.det_threshold.value(),
                led_start=0,
                led_end=total,
                resume_preview=self._wants_live_feed(),
            )
            self.btn_det_scan.setEnabled(False)
            self.det_status.setText(
                f"Scanning {total} LEDs from one camera angle — 2D map opens when done…"
            )
        except Exception as error:
            self._on_detection_error(str(error))

    def _on_test_finished(self, result) -> None:
        self.btn_det_test.setEnabled(True)
        led_id = self.det_current_id.value()
        if result is None:
            self.det_status.setText(f"LED {led_id}: not detected")
        else:
            self.det_status.setText(
                f"LED {led_id}: detected at u={result.point.u():.3f} v={result.point.v():.3f}"
            )
        if self._wants_live_feed():
            self.start_live_view()

    def _on_scan_progress(self, index: int, total: int, result) -> None:
        if result is None:
            self.det_status.setText(f"Scan {index + 1}/{total}: missed")
        else:
            self.det_status.setText(
                f"Scan {index + 1}/{total}: LED {result.led_id} OK "
                f"u={result.point.u():.3f} v={result.point.v():.3f}"
            )
            self.det_current_id.setValue(result.led_id)

    def _on_scan_finished(
        self, detected: int, total: int, results, reference_frame
    ) -> None:
        self.btn_det_scan.setEnabled(True)
        leds: list[LED2D] = list(results) if results else []

        if leds:
            if self._map_results_window is not None:
                self._map_results_window.close()
            self._map_results_window = MapResultsWindow(
                leds,
                total,
                reference_frame=reference_frame,
                parent=None,
            )
            self._map_results_window.show()
            self._map_results_window.raise_()
            self._map_results_window.activateWindow()
            self.det_status.setText(
                f"Scan done: {detected}/{total} detected — 2D map window open."
            )
        else:
            self.det_status.setText(
                f"Scan done: 0/{total} detected — no map to show."
            )

        if self._wants_live_feed():
            self.start_live_view()

    def _on_detection_error(self, message: str) -> None:
        self.stop_camera()
        self.det_status.setText(f"Error: {message}")
