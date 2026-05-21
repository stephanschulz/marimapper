"""Window showing 2D LED maps from saved CSV files."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from marimapper.detection_map_viz import make_map_canvas
from marimapper.dmx.draggable_map import DraggableLedMapWidget
from marimapper.dmx.roi_preview import LabeledPreview
from marimapper.dmx.scan_paths import default_scan_dir, ensure_scan_dir, migrate_legacy_scans
from marimapper.file_tools import (
    fill_missing_leds,
    is_led_missing,
    list_2d_map_csv_files,
    load_detections,
    load_map_capture_image,
    load_map_dmx_settings,
    load_map_scan_total,
    save_map_annotated_image,
    save_map_capture_image,
    save_map_scan_meta,
    write_2d_leds_to_file,
)
from marimapper.led import LED2D

if TYPE_CHECKING:
    from marimapper.dmx.gui import DmxControllerWindow


class MapResultsWindow(QMainWindow):
    """Browse and view 2D LED maps saved as CSV."""

    def __init__(
        self,
        parent=None,
        maps_dir: Path | None = None,
        controller: "DmxControllerWindow | None" = None,
    ):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self._maps_dir = maps_dir or ensure_scan_dir()
        migrate_legacy_scans()
        self._scan_totals: dict[str, int] = {}
        self._current_csv: Path | None = None
        self._controller = controller
        self._current_total: int = 0
        self._current_min_channel: int = 1
        self._current_channels_per_fixture: int = 1
        self._current_reference_frame = None

        self.setWindowTitle("2D LED map")
        self.setMinimumSize(900, 640)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Map CSV:"))
        self._csv_combo = QComboBox()
        self._csv_combo.setMinimumWidth(320)
        self._csv_combo.currentIndexChanged.connect(self._on_csv_selected)
        picker_row.addWidget(self._csv_combo, stretch=1)
        self._btn_refresh = QPushButton("Refresh")
        # QPushButton.clicked emits a `checked` bool — discard it so it doesn't
        # get passed as ``select_path``.
        self._btn_refresh.clicked.connect(lambda: self._refresh_csv_list())
        picker_row.addWidget(self._btn_refresh)
        layout.addLayout(picker_row)

        self._summary = QLabel(
            "Select a CSV map or run a scan to capture a new one. "
            "Drag a crosshair to fire its DMX channel at 255 while held."
        )
        self._summary.setWordWrap(True)
        self._summary.setFont(QFont("Helvetica", 11))
        layout.addWidget(self._summary)

        content = QHBoxLayout()
        self._preview = DraggableLedMapWidget()
        self._preview.led_grabbed.connect(self._on_led_grabbed)
        self._preview.led_moved.connect(self._on_led_moved)
        self._preview.led_released.connect(self._on_led_released)
        content.addWidget(LabeledPreview("Mapped LEDs", self._preview), stretch=2)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Index", "DMX", "u", "v"])
        content.addWidget(self._table, stretch=1)
        layout.addLayout(content, stretch=1)

        btn_row = QHBoxLayout()
        self._path_label = QLabel("")
        self._path_label.setWordWrap(True)
        btn_row.addWidget(self._path_label, stretch=1)
        self._btn_save = QPushButton("Save CSV as…")
        self._btn_save.clicked.connect(self._save_as)
        btn_row.addWidget(self._btn_save)
        layout.addLayout(btn_row)

        self._refresh_csv_list()

    def set_controller(self, controller: "DmxControllerWindow | None") -> None:
        self._controller = controller

    def set_live_frame(self, frame) -> None:
        """Update the live camera background behind the map."""
        if not self.isVisible():
            return
        self._preview.set_live_frame(frame)

    def _refresh_csv_list(self, select_path: Path | None = None) -> None:
        self._csv_combo.blockSignals(True)
        self._csv_combo.clear()
        paths = list_2d_map_csv_files(self._maps_dir)
        for path in paths:
            self._csv_combo.addItem(path.name, str(path.resolve()))
        self._csv_combo.blockSignals(False)

        if select_path is not None:
            index = self._csv_combo.findData(str(select_path.resolve()))
            if index >= 0:
                self._csv_combo.setCurrentIndex(index)
                return
        if self._csv_combo.count() > 0:
            self._csv_combo.setCurrentIndex(0)
        elif select_path is None:
            self._clear_display()

    def _on_csv_selected(self, _index: int) -> None:
        path_data = self._csv_combo.currentData()
        if not path_data:
            self._clear_display()
            return
        self.load_csv(Path(path_data))

    def load_csv(self, path: Path) -> None:
        leds = load_detections(path, 0)
        if leds is None:
            self._summary.setText(f"Could not load map: {path}")
            return
        self._current_csv = path.resolve()
        reference_frame = load_map_capture_image(self._current_csv)
        total = load_map_scan_total(
            self._current_csv,
            self._scan_totals.get(str(self._current_csv), len(leds)),
        )
        min_channel, channels_per_fixture = load_map_dmx_settings(self._current_csv)
        self._display_leds(
            leds, total, reference_frame, min_channel, channels_per_fixture
        )
        self._path_label.setText(str(self._current_csv))

    def show_new_capture(
        self,
        leds: list[LED2D],
        total: int,
        reference_frame=None,
        csv_path: Path | None = None,
        *,
        min_channel: int = 1,
        channels_per_fixture: int = 1,
    ) -> Path | None:
        """Save (if needed), refresh list, select new CSV, and display."""
        path = csv_path
        if path is None:
            path = self._default_save_path()
        # Every DMX channel gets a row; undetected scans land at (-1, -1).
        full_leds = fill_missing_leds(leds, total)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_2d_leds_to_file(
                full_leds,
                path,
                min_channel=min_channel,
                channels_per_fixture=channels_per_fixture,
            )
        except OSError as error:
            self._summary.setText(f"Could not save CSV: {error}")
            return None

        path = path.resolve()
        if reference_frame is not None:
            save_map_capture_image(path, reference_frame)
            save_map_annotated_image(
                path,
                reference_frame,
                full_leds,
                min_channel=min_channel,
                channels_per_fixture=channels_per_fixture,
            )
        save_map_scan_meta(
            path,
            total,
            min_channel=min_channel,
            channels_per_fixture=channels_per_fixture,
        )
        self._scan_totals[str(path)] = total
        self._refresh_csv_list(select_path=path)
        self.show()
        self.raise_()
        self.activateWindow()
        return path

    def _display_leds(
        self,
        leds: list[LED2D],
        total: int,
        reference_frame,
        min_channel: int = 1,
        channels_per_fixture: int = 1,
    ) -> None:
        full_leds = fill_missing_leds(leds, total)
        detected = sum(1 for led in full_leds if not is_led_missing(led))
        missed = sum(1 for led in full_leds if is_led_missing(led))
        self._summary.setText(
            "Single camera view — 2D map only (no multi-angle 3D reconstruction). "
            f"Showing {detected} LED(s)"
            + (f" ({missed} missed — saved at -1,-1)" if missed else "")
            + ". Drag a crosshair to fire its DMX channel at 255 while held."
        )
        base = reference_frame if reference_frame is not None else make_map_canvas()
        self._preview.set_dmx_mapping(min_channel, channels_per_fixture)
        self._preview.set_map(base, full_leds)
        self._current_total = max(total, len(full_leds))
        self._current_min_channel = min_channel
        self._current_channels_per_fixture = channels_per_fixture
        self._current_reference_frame = base
        self._populate_table(full_leds)

    def _populate_table(self, leds: list[LED2D]) -> None:
        sorted_leds = sorted(leds, key=lambda item: item.led_id)
        self._table.setRowCount(len(sorted_leds))
        for row, led in enumerate(sorted_leds):
            dmx = self._current_min_channel + led.led_id * self._current_channels_per_fixture
            self._table.setItem(row, 0, QTableWidgetItem(str(led.led_id)))
            self._table.setItem(row, 1, QTableWidgetItem(str(dmx)))
            if is_led_missing(led):
                self._table.setItem(row, 2, QTableWidgetItem("—"))
                self._table.setItem(row, 3, QTableWidgetItem("—"))
            else:
                self._table.setItem(row, 2, QTableWidgetItem(f"{led.point.u():.6f}"))
                self._table.setItem(row, 3, QTableWidgetItem(f"{led.point.v():.6f}"))
        self._table.resizeColumnsToContents()

    def _update_table_row(self, led_id: int, u: float, v: float) -> None:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is not None and item.text() == str(led_id):
                if u < 0.0 or v < 0.0:
                    self._table.setItem(row, 2, QTableWidgetItem("—"))
                    self._table.setItem(row, 3, QTableWidgetItem("—"))
                else:
                    self._table.setItem(row, 2, QTableWidgetItem(f"{u:.6f}"))
                    self._table.setItem(row, 3, QTableWidgetItem(f"{v:.6f}"))
                return

    # ---- crosshair drag → DMX -------------------------------------------

    def _on_led_grabbed(self, led_id: int) -> None:
        if self._controller is None:
            self._summary.setText(
                f"LED {led_id} grabbed — controller not wired, no DMX sent."
            )
            return
        try:
            dmx_ch, level = self._controller.highlight_detection_led(led_id)
        except Exception as error:
            self._summary.setText(f"DMX highlight failed: {error}")
            return
        self._summary.setText(
            f"Holding LED {led_id} → DMX ch {dmx_ch} = {level}. Drop to clear."
        )

    def _on_led_moved(self, led_id: int, u: float, v: float) -> None:
        self._update_table_row(led_id, u, v)

    def _on_led_released(self, led_id: int) -> None:
        if self._controller is not None:
            try:
                backend = self._controller.build_detection_backend()
                backend.all_off()
            except Exception as error:
                self._summary.setText(
                    f"LED {led_id} released — could not clear DMX: {error}"
                )
                return
        # Persist the new position to CSV next to the existing map.
        leds = self._preview.leds()
        path = self._current_csv
        if path is not None:
            try:
                write_2d_leds_to_file(
                    leds,
                    path,
                    min_channel=self._current_min_channel,
                    channels_per_fixture=self._current_channels_per_fixture,
                )
                if self._current_reference_frame is not None:
                    save_map_annotated_image(
                        path,
                        self._current_reference_frame,
                        leds,
                        min_channel=self._current_min_channel,
                        channels_per_fixture=self._current_channels_per_fixture,
                    )
                self._summary.setText(
                    f"LED {led_id} dropped — saved updated map to {path.name}."
                )
                return
            except OSError as error:
                self._summary.setText(
                    f"LED {led_id} dropped — could not save CSV: {error}"
                )
                return
        self._summary.setText(f"LED {led_id} dropped — DMX cleared.")

    def _clear_display(self) -> None:
        self._preview.clear()
        self._table.setRowCount(0)
        self._path_label.setText(f"No maps in {self._maps_dir}")
        self._current_total = 0
        self._current_reference_frame = None

    @staticmethod
    def _default_save_path() -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return default_scan_dir() / f"led_map_2d_{stamp}.csv"

    def _save_as(self) -> None:
        path_data = self._csv_combo.currentData()
        start = str(path_data) if path_data else str(self._maps_dir)
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save 2D LED map",
            start,
            "CSV (*.csv)",
        )
        if not filename or self._current_csv is None:
            return
        leds = load_detections(self._current_csv, 0)
        if leds is None:
            return
        try:
            dest = Path(filename).resolve()
            min_channel, channels_per_fixture = load_map_dmx_settings(
                self._current_csv
            )
            total = load_map_scan_total(self._current_csv, len(leds))
            full_leds = fill_missing_leds(leds, total)
            write_2d_leds_to_file(
                full_leds,
                dest,
                min_channel=min_channel,
                channels_per_fixture=channels_per_fixture,
            )
            frame = load_map_capture_image(self._current_csv)
            if frame is not None:
                save_map_capture_image(dest, frame)
                save_map_annotated_image(
                    dest,
                    frame,
                    full_leds,
                    min_channel=min_channel,
                    channels_per_fixture=channels_per_fixture,
                )
            save_map_scan_meta(
                dest,
                total,
                min_channel=min_channel,
                channels_per_fixture=channels_per_fixture,
            )
            self._refresh_csv_list(select_path=dest)
        except OSError as error:
            self._summary.setText(f"Could not save CSV: {error}")
