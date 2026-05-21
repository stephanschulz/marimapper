"""Separate window for camera preview and LED detection."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from marimapper.camera_devices import (
    default_camera_index,
    list_cameras,
    probe_single_camera,
)
from marimapper.detection_roi import DetectionRoi
from marimapper.dmx.detection_worker import SharedDetectionCameraWorker
from marimapper.dmx.map_results_window import MapResultsWindow
from marimapper.dmx.roi_preview import FramePreviewWidget, LabeledPreview, RoiPreviewWidget
from marimapper.led import LED2D


if sys.platform == "darwin":
    from marimapper.dmx.uvc_controls_panel import UvcControlsPanel

if TYPE_CHECKING:
    from marimapper.dmx.gui import DmxControllerWindow


class CameraDetectionWindow(QMainWindow):
    """Live camera feed + detection controls (preview stays on during test/scan)."""

    def __init__(self, controller: DmxControllerWindow):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Camera — LED detection")
        self.setMinimumSize(1024, 640)

        self._camera_worker: SharedDetectionCameraWorker | None = None
        self._pending_camera: int | None = None
        self._pending_camera_name: str | None = None
        self._pending_uvc: dict = {}
        self._live_view_enabled = True
        self._map_results_window: MapResultsWindow | None = None
        self._scan_accumulated: list[LED2D] = []
        self._last_scan_leds: list[LED2D] = []
        self._last_scan_total = 0
        self._last_scan_frame = None
        self._initial_camera_populated = False
        self._suppress_camera_change = False

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        preview_column = QVBoxLayout()
        preview_column.setSpacing(6)
        self.det_preview = RoiPreviewWidget()
        self.det_preview.roi_changed.connect(self._on_roi_changed)
        self.det_threshold_preview = FramePreviewWidget()
        preview_column.addWidget(
            LabeledPreview("Live camera", self.det_preview), stretch=1
        )
        preview_column.addWidget(
            LabeledPreview("Threshold view (detection input)", self.det_threshold_preview),
            stretch=1,
        )

        preview_host = QWidget()
        preview_host.setLayout(preview_column)
        preview_host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(preview_host, stretch=1)

        sidebar = QScrollArea()
        sidebar.setWidgetResizable(True)
        sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar.setFrameShape(QScrollArea.Shape.NoFrame)
        sidebar.setMinimumWidth(280)
        sidebar.setMaximumWidth(340)
        sidebar.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )

        sidebar_content = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_content)
        sidebar_layout.setContentsMargins(0, 0, 4, 0)
        sidebar_layout.setSpacing(8)

        roi_group = QGroupBox("Region of interest")
        roi_layout = QVBoxLayout(roi_group)
        self.btn_roi_draw = QPushButton("Draw ROI")
        self.btn_roi_draw.setCheckable(True)
        self.btn_roi_draw.clicked.connect(self._toggle_roi_draw)
        roi_layout.addWidget(self.btn_roi_draw)
        self.btn_roi_clear = QPushButton("Clear ROI")
        self.btn_roi_clear.clicked.connect(self._clear_roi)
        roi_layout.addWidget(self.btn_roi_clear)
        sidebar_layout.addWidget(roi_group)

        controls = QGroupBox("Camera & detection")
        form = QFormLayout(controls)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.det_camera_combo = QComboBox()
        self.det_camera_combo.currentIndexChanged.connect(self._on_camera_changed)
        form.addRow("Camera:", self.det_camera_combo)

        self.det_camera_refresh = QPushButton("Refresh camera list")
        self.det_camera_refresh.clicked.connect(self.refresh_cameras)
        form.addRow("", self.det_camera_refresh)

        self.det_exposure = QSpinBox()
        self.det_exposure.setRange(-13, 0)
        self.det_exposure.setValue(-10)
        self.det_exposure.setToolTip(
            "0 = auto where supported. Negative = darker (software on macOS for BRIO)."
        )
        self.det_exposure.valueChanged.connect(self._on_det_exposure_changed)
        form.addRow("Exposure:", self.det_exposure)

        self.det_threshold = QSpinBox()
        self.det_threshold.setRange(0, 255)
        self.det_threshold.setValue(128)
        self.det_threshold.setToolTip(
            "Brightness cutoff (0–255). Higher = only brighter pixels count; "
            "lower = more sensitive. Threshold preview shows this live."
        )
        self.det_threshold.valueChanged.connect(self._on_threshold_changed)
        form.addRow("Threshold:", self.det_threshold)

        self.det_frame_diff = QCheckBox("Frame difference (averaged background)")
        self.det_frame_diff.setChecked(True)
        self.det_frame_diff.setToolTip(
            "Learn background while LEDs are off, then detect bright flashes. "
            "Works better than a global threshold on a dark image. Preview shows the diff."
        )
        self.det_frame_diff.toggled.connect(self._on_frame_diff_toggled)
        form.addRow("", self.det_frame_diff)

        self.det_current_id = QSpinBox()
        self.det_current_id.setRange(0, 9999)
        self.det_current_id.setValue(0)
        self.det_current_id.valueChanged.connect(self._on_led_index_changed)
        form.addRow("LED index:", self.det_current_id)

        self.btn_det_test = QPushButton("Test this ID")
        self.btn_det_test.clicked.connect(self.test_detection_id)
        form.addRow("", self.btn_det_test)

        self.btn_det_pause = QPushButton("Pause live view")
        self.btn_det_pause.setCheckable(True)
        self.btn_det_pause.clicked.connect(self.toggle_pause_live_view)
        form.addRow("", self.btn_det_pause)

        self.btn_det_scan = QPushButton("Run 2D detection scan")
        self.btn_det_scan.setToolTip(
            "Scan every LED from one camera angle. Opens a 2D map when done "
            "(multi-angle 3D reconstruction is not required)."
        )
        self.btn_det_scan.clicked.connect(self.toggle_detection_scan)
        form.addRow("", self.btn_det_scan)

        self.btn_det_stop = QPushButton("Stop camera")
        self.btn_det_stop.clicked.connect(self.stop_camera)
        form.addRow("", self.btn_det_stop)

        sidebar_layout.addWidget(controls)

        self.btn_show_map = QPushButton("Show 2D map")
        self.btn_show_map.setEnabled(False)
        self.btn_show_map.clicked.connect(self._reopen_scan_map)
        sidebar_layout.addWidget(self.btn_show_map)

        self.uvc_panel: UvcControlsPanel | None = None
        if sys.platform == "darwin":
            self.uvc_panel = UvcControlsPanel(self.selected_camera_index)
            sidebar_layout.addWidget(self.uvc_panel)

        self.det_status = QLabel(
            "Live preview, exposure, ROI, test, and 2D scan run in this window. "
            "The feed stays on during test and scan."
        )
        self.det_status.setWordWrap(True)
        self.det_status.setFont(QFont("Helvetica", 11))
        self.det_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.det_status.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self.det_status.setMinimumHeight(48)
        self.det_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        sidebar_layout.addWidget(self.det_status)

        sidebar.setWidget(sidebar_content)
        root.addWidget(sidebar)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.det_camera_combo.count() == 0:
            self._fast_initial_camera_setup()
        self._sync_led_index_range()
        self._on_led_index_changed(self.det_current_id.value())
        self._ensure_map_window()
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
        self._pending_camera_name = settings.get("det_camera_name") or None
        self.det_exposure.setValue(settings.get("det_exposure", -10))
        self.det_threshold.setValue(settings.get("det_threshold", 128))
        self.det_frame_diff.setChecked(settings.get("det_frame_diff", True))
        self.det_current_id.setValue(settings.get("det_current_id", 0))
        self._pending_uvc = settings.get("det_uvc", {})
        self.det_preview.set_roi(DetectionRoi.from_list(settings.get("det_roi")))
        self._sync_roi_to_worker()
        if self.isVisible():
            self.refresh_cameras()
        elif self.uvc_panel is not None:
            self._refresh_uvc_panel()

    def settings_snapshot(self) -> dict:
        snapshot = {
            "det_camera": self.selected_camera_index(),
            "det_camera_name": self.det_camera_combo.currentText(),
            "det_exposure": self.det_exposure.value(),
            "det_threshold": self.det_threshold.value(),
            "det_frame_diff": self.det_frame_diff.isChecked(),
            "det_current_id": self.det_current_id.value(),
            "det_roi": self.det_preview.roi().to_list(),
        }
        if self.uvc_panel is not None:
            snapshot["det_uvc"] = self.uvc_panel.values_snapshot()
        return snapshot

    def _on_camera_changed(self, _index: int) -> None:
        if self._suppress_camera_change:
            return
        self._refresh_uvc_panel()
        # If preview is already running, switch to the newly selected device.
        if (
            self._camera_worker is not None
            and self._camera_worker.isRunning()
            and self._wants_live_feed()
        ):
            self.det_status.setText(
                f"Switching camera to {self.det_camera_combo.currentText()}…"
            )
            self.start_live_view()

    def _fast_initial_camera_setup(self) -> None:
        """
        Try the last-selected camera and stop there.

        We saved both index and label last session. AVFoundation can reorder
        indexes when devices come and go (e.g. an iPhone now occupies what used
        to be the BRIO's slot), so we verify by label. If the saved camera is
        present we use it and DO NOT probe other indexes — probing them would
        steal iPhone Continuity Camera and interfere with the active capture.
        If the saved camera is gone, only then do we enumerate.
        """
        if self._initial_camera_populated:
            return
        self._initial_camera_populated = True
        target = self._pending_camera if self._pending_camera is not None else 0
        saved_name = self._pending_camera_name

        probe = probe_single_camera(target) if isinstance(target, int) else None
        if probe is not None and self._labels_match(probe[1], saved_name):
            index, label = probe
            self._populate_single_camera(index, label)
            self.det_status.setText(
                f"Using saved camera {label}. Click Refresh to scan for others."
            )
            return

        # Saved camera missing — fall back to full synchronous enumeration.
        self._initial_camera_populated = False
        if saved_name is not None and probe is not None:
            self.det_status.setText(
                f"Saved camera '{saved_name}' moved — scanning for it…"
            )
        self.refresh_cameras()

    @staticmethod
    def _labels_match(label: str, saved_name: str | None) -> bool:
        """Match the device portion of '[i] Name — note' labels."""
        if not saved_name:
            return True

        def core(text: str) -> str:
            text = text.split("]", 1)[-1].strip()
            text = text.split(" — ", 1)[0].strip()
            return text.lower()

        return core(label) == core(saved_name)

    def _populate_single_camera(self, index: int, label: str) -> None:
        self._suppress_camera_change = True
        self.det_camera_combo.clear()
        self.det_camera_combo.addItem(label, index)
        self.det_camera_combo.setCurrentIndex(0)
        self._suppress_camera_change = False
        self._pending_camera = None
        self._refresh_uvc_panel()

    def _refresh_uvc_panel(self) -> None:
        if self.uvc_panel is None:
            return
        self.uvc_panel.refresh_from_device()
        if self._pending_uvc:
            self.uvc_panel.apply_saved_values(self._pending_uvc)
            self._pending_uvc = {}

    def refresh_cameras(self) -> None:
        current = self.det_camera_combo.currentData()
        self._suppress_camera_change = True
        self.det_camera_combo.clear()
        cameras = list_cameras()
        if not cameras:
            self.det_camera_combo.addItem("No camera found", 0)
            self.det_status.setText("No camera detected — check USB and permissions.")
            self._suppress_camera_change = False
            return

        for index, label in cameras:
            self.det_camera_combo.addItem(label, index)

        selected = self._select_camera_after_refresh(cameras, current)
        if selected is not None:
            self.det_camera_combo.setCurrentIndex(selected)
        self._pending_camera = None
        self._pending_camera_name = None
        self._initial_camera_populated = True
        self._suppress_camera_change = False
        self._refresh_uvc_panel()

        if self._live_view_enabled and not self.btn_det_pause.isChecked():
            self.start_live_view()

    def _select_camera_after_refresh(
        self, cameras: list, current
    ) -> int | None:
        """Pick best dropdown index after refresh: saved name, saved index, then default."""
        if self._pending_camera_name:
            for combo_index in range(self.det_camera_combo.count()):
                if self._labels_match(
                    self.det_camera_combo.itemText(combo_index),
                    self._pending_camera_name,
                ):
                    return combo_index

        restore = self._pending_camera if self._pending_camera is not None else current
        if restore is not None:
            idx = self.det_camera_combo.findData(restore)
            if idx >= 0:
                return idx

        prefer = default_camera_index(cameras)
        idx = self.det_camera_combo.findData(prefer)
        return idx if idx >= 0 else None

    def show_detection_frame(self, camera_frame, threshold_frame=None) -> None:
        self.det_preview.set_frame(camera_frame)
        if threshold_frame is not None:
            self.det_threshold_preview.set_frame(threshold_frame)
        if self._map_results_window is not None:
            self._map_results_window.set_live_frame(camera_frame)

    def _sync_roi_to_worker(self) -> None:
        if self._camera_worker is not None and self._camera_worker.isRunning():
            self._camera_worker.set_roi(self.det_preview.roi())

    def _on_roi_changed(self, _roi: DetectionRoi) -> None:
        self._sync_roi_to_worker()
        if self.det_preview.roi().is_valid():
            self.btn_roi_draw.setChecked(False)
            n = len(self.det_preview.roi().points)
            self.det_status.setText(f"ROI set — detection limited to {n}-point polygon.")
        elif not self.det_preview.is_drawing():
            self.det_status.setText("ROI cleared — full frame used for detection.")

    def _toggle_roi_draw(self, checked: bool) -> None:
        if checked:
            self.det_preview.start_drawing()
            self.det_status.setText(
                "ROI draw mode: click corners, double-click to close (min 3 points)."
            )
        else:
            self.det_preview.cancel_drawing()

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
            self._scan_accumulated = []
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
        if result is None or result.point is None:
            self.det_status.setText(f"LED {led_id}: not detected")
        else:
            self.det_status.setText(
                f"LED {led_id}: detected at u={result.point.u():.3f} v={result.point.v():.3f}"
            )
        if self._wants_live_feed():
            self.start_live_view()

    def _on_scan_progress(self, index: int, total: int, result) -> None:
        if result is not None and result.point is not None:
            self._scan_accumulated.append(result)
            self.det_status.setText(
                f"Scan {index + 1}/{total}: LED {result.led_id} OK "
                f"u={result.point.u():.3f} v={result.point.v():.3f}"
            )
            self.det_current_id.setValue(result.led_id)
        else:
            self.det_status.setText(f"Scan {index + 1}/{total}: missed")

    def _collect_scan_results(self) -> tuple[list[LED2D], object | None]:
        leds: list[LED2D] = []
        reference_frame = None
        if self._camera_worker is not None:
            leds = list(self._camera_worker.last_scan_results)
            reference_frame = self._camera_worker.last_scan_reference_frame
        if not leds:
            leds = list(self._scan_accumulated)
        return leds, reference_frame

    def _present_scan_map(self, detected: int, total: int) -> None:
        leds, reference_frame = self._collect_scan_results()
        self._last_scan_leds = leds
        self._last_scan_total = total
        self._last_scan_frame = reference_frame
        self.btn_show_map.setEnabled(bool(leds))

        if not leds:
            self.det_status.setText(
                f"Scan done: 0/{total} detected — no map to show."
            )
            if self._wants_live_feed():
                self.start_live_view()
            return

        try:
            self.det_status.setText(
                f"Scan done: {detected}/{total} detected — updating 2D map window…"
            )
            QTimer.singleShot(
                0,
                lambda: self._open_map_window(leds, total, reference_frame),
            )
        except Exception as error:
            QMessageBox.warning(
                self,
                "2D map error",
                f"Scan finished but the map could not be saved:\n{error}",
            )
            self.det_status.setText(f"Scan done: {detected}/{total} — map error: {error}")

        if self._wants_live_feed():
            self.start_live_view()

    def _ensure_map_window(self) -> MapResultsWindow:
        if self._map_results_window is None:
            self._map_results_window = MapResultsWindow(
                parent=None, controller=self.controller
            )
        else:
            self._map_results_window.set_controller(self.controller)
        self._map_results_window.show()
        return self._map_results_window

    def _open_map_window(
        self, leds: list[LED2D], total: int, reference_frame
    ) -> None:
        try:
            window = self._ensure_map_window()
            config = self.controller.build_detection_backend().config
            path = window.show_new_capture(
                leds,
                total,
                reference_frame,
                min_channel=config.min_channel,
                channels_per_fixture=config.channels_per_fixture,
            )
            if path is not None:
                self.det_status.setText(
                    f"Scan done: {len(leds)}/{total} detected — map: {path.name}"
                )
        except Exception as error:
            QMessageBox.warning(
                self,
                "2D map window",
                f"Could not update the map window:\n{error}",
            )

    def _reopen_scan_map(self) -> None:
        if self._last_scan_leds:
            self._open_map_window(
                self._last_scan_leds,
                self._last_scan_total,
                self._last_scan_frame,
            )
            return
        window = self._ensure_map_window()
        window.raise_()
        window.activateWindow()

    def _on_scan_finished(self, detected: int, total: int) -> None:
        self.btn_det_scan.setEnabled(True)
        self._present_scan_map(detected, total)

    def _on_detection_error(self, message: str) -> None:
        self.stop_camera()
        self.det_status.setText(f"Error: {message}")
