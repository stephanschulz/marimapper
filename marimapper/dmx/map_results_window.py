"""Window showing a single-view 2D LED map after detection scan."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
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

from marimapper.detection_map_viz import draw_led_map, make_map_canvas
from marimapper.dmx.roi_preview import FramePreviewWidget, LabeledPreview
from marimapper.file_tools import write_2d_leds_to_file
from marimapper.led import LED2D


class MapResultsWindow(QMainWindow):
    """Display normalized 2D LED positions from one camera angle."""

    def __init__(
        self,
        leds: list[LED2D],
        total: int,
        reference_frame=None,
        save_path: Path | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self._leds = list(leds)
        self._total = total
        self._save_path = save_path or self._default_save_path()
        self.setWindowTitle("2D LED map")
        self.setMinimumSize(900, 640)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        detected = len(self._leds)
        missed = total - detected
        self._summary = QLabel(
            f"Single camera view — 2D map only (no multi-angle 3D reconstruction). "
            f"Detected {detected}/{total} LEDs"
            + (f" ({missed} missed)." if missed else ".")
        )
        self._summary.setWordWrap(True)
        self._summary.setFont(QFont("Helvetica", 11))
        layout.addWidget(self._summary)

        content = QHBoxLayout()
        base = reference_frame if reference_frame is not None else make_map_canvas()
        overlay = draw_led_map(base, self._leds)
        self._preview = FramePreviewWidget()
        self._preview.set_frame(overlay)
        content.addWidget(LabeledPreview("Mapped LEDs", self._preview), stretch=2)

        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Index", "u", "v"])
        self._table.setRowCount(len(self._leds))
        for row, led in enumerate(sorted(self._leds, key=lambda item: item.led_id)):
            self._table.setItem(row, 0, QTableWidgetItem(str(led.led_id)))
            self._table.setItem(row, 1, QTableWidgetItem(f"{led.point.u():.6f}"))
            self._table.setItem(row, 2, QTableWidgetItem(f"{led.point.v():.6f}"))
        self._table.resizeColumnsToContents()
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

        self._try_save_csv(self._save_path)

    @staticmethod
    def _default_save_path() -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return Path.home() / "marimapper_maps" / f"led_map_2d_{stamp}.csv"

    def _try_save_csv(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_2d_leds_to_file(self._leds, path)
            self._save_path = path
            self._path_label.setText(f"Saved to: {path}")
        except OSError as error:
            self._path_label.setText(f"Could not save CSV ({error}). Use Save CSV as…")

    def _save_as(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save 2D LED map",
            str(self._save_path),
            "CSV (*.csv)",
        )
        if filename:
            self._try_save_csv(Path(filename))
