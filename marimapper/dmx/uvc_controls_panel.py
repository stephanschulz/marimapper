"""Hardware UVC control sliders (macOS / uvc-util)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from marimapper.camera_uvc_mac import (
    UVC_GUI_CONTROL_NAMES,
    UVC_GUI_LABELS,
    read_uvc_control,
    reset_uvc_controls,
    set_uvc_control,
    uvc_available,
)


class UvcControlsPanel(QGroupBox):
    """Sliders and toggles for BRIO / UVC camera hardware controls."""

    def __init__(
        self,
        device_index_getter: Callable[[], int],
        parent=None,
    ):
        super().__init__("UVC hardware controls", parent)
        self._device_index_getter = device_index_getter
        self._widgets: dict[str, QSlider | QCheckBox] = {}
        self._labels: dict[str, QLabel] = {}
        self._pending: dict[str, int | bool] = {}
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(80)
        self._apply_timer.timeout.connect(self._apply_pending)
        self._loading = False
        self._control_infos: list = []

        outer = QVBoxLayout(self)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        self._btn_refresh = QPushButton("Read from camera")
        self._btn_refresh.clicked.connect(self.refresh_from_device)
        outer.addWidget(self._btn_refresh)

        self._btn_reset = QPushButton("Reset defaults")
        self._btn_reset.clicked.connect(self._reset_defaults)
        outer.addWidget(self._btn_reset)

        self._grid_host = QWidget()
        self._grid = QVBoxLayout(self._grid_host)
        self._grid.setSpacing(6)
        outer.addWidget(self._grid_host)

        if not uvc_available():
            self._status.setText(
                "uvc-util not available. Install Xcode CLT or run scripts/build_uvc_util.sh"
            )
            self._btn_refresh.setEnabled(False)
            self._btn_reset.setEnabled(False)
        else:
            self._status.setText("Hardware controls via uvc-util.")

    def refresh_from_device(self) -> None:
        if not uvc_available():
            return
        device_index = self._device_index_getter()
        self._clear_grid()
        self._loading = True
        try:
            self._control_infos = []
            for name in UVC_GUI_CONTROL_NAMES:
                info = read_uvc_control(device_index, name)
                if info is not None:
                    self._control_infos.append(info)
            self._layout_controls_vertical()
            self._sync_auto_dependencies()
            if not self._widgets:
                self._status.setText("No UVC controls found for this camera.")
            else:
                self._status.setText(
                    f"{len(self._widgets)} UVC control(s) loaded."
                )
        finally:
            self._loading = False

    def apply_saved_values(self, values: dict) -> None:
        if not values or not uvc_available():
            return
        device_index = self._device_index_getter()
        for name, value in values.items():
            if name not in self._widgets:
                continue
            widget = self._widgets[name]
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QSlider):
                widget.setValue(int(value))
            set_uvc_control(device_index, name, value)
        self._sync_auto_dependencies()

    def values_snapshot(self) -> dict[str, int | bool]:
        out: dict[str, int | bool] = {}
        for name, widget in self._widgets.items():
            if isinstance(widget, QCheckBox):
                out[name] = widget.isChecked()
            elif isinstance(widget, QSlider):
                out[name] = widget.value()
        return out

    def _clear_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._widgets.clear()
        self._labels.clear()
        self._control_infos.clear()

    def _layout_controls_vertical(self) -> None:
        for info in self._control_infos:
            cell = self._make_control_cell(info)
            self._grid.addWidget(cell)

    def _make_control_cell(self, info) -> QWidget:
        label_text = UVC_GUI_LABELS.get(info.name, info.name)
        cell = QWidget()
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        label = QLabel(label_text)
        layout.addWidget(label)

        if info.kind == "bool":
            checkbox = QCheckBox()
            checkbox.setChecked(bool(info.current))
            checkbox.toggled.connect(
                lambda checked, n=info.name: self._queue_apply(n, checked)
            )
            layout.addWidget(checkbox)
            self._widgets[info.name] = checkbox
            return cell

        slider_row = QHBoxLayout()
        slider = QSlider(Qt.Orientation.Horizontal)
        minimum = int(info.minimum if info.minimum is not None else 0)
        maximum = int(info.maximum if info.maximum is not None else 255)
        step = int(info.step if info.step is not None else 1)
        slider.setMinimum(minimum)
        slider.setMaximum(maximum)
        slider.setSingleStep(max(1, step))
        slider.setPageStep(max(step, (maximum - minimum) // 20 or 1))
        if info.current is not None:
            slider.setValue(int(info.current))
        value_label = QLabel(str(slider.value()))
        value_label.setMinimumWidth(36)
        value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        slider.valueChanged.connect(
            lambda val, lbl=value_label: lbl.setText(str(val))
        )
        slider.valueChanged.connect(
            lambda val, n=info.name: self._queue_apply(n, val)
        )
        slider_row.addWidget(slider, stretch=1)
        slider_row.addWidget(value_label)
        layout.addLayout(slider_row)
        self._widgets[info.name] = slider
        self._labels[info.name] = value_label
        return cell

    def _queue_apply(self, name: str, value: int | bool) -> None:
        if self._loading:
            return
        self._pending[name] = value
        self._apply_timer.start()

    def _apply_pending(self) -> None:
        if not self._pending or not uvc_available():
            return
        device_index = self._device_index_getter()
        errors: list[str] = []
        pending = dict(self._pending)
        self._pending.clear()
        for name, value in pending.items():
            ok, msg = set_uvc_control(device_index, name, value)
            if not ok:
                errors.append(f"{name}: {msg}")
        self._sync_auto_dependencies()
        if errors:
            self._status.setText("UVC: " + "; ".join(errors[:2]))
        else:
            self._status.setText("UVC controls applied.")

    def _sync_auto_dependencies(self) -> None:
        auto_focus = self._widgets.get("auto-focus")
        focus = self._widgets.get("focus-abs")
        if isinstance(auto_focus, QCheckBox) and isinstance(focus, QSlider):
            focus.setEnabled(not auto_focus.isChecked())

        auto_wb = self._widgets.get("auto-white-balance-temp")
        wb = self._widgets.get("white-balance-temp")
        if isinstance(auto_wb, QCheckBox) and isinstance(wb, QSlider):
            wb.setEnabled(not auto_wb.isChecked())

    def _reset_defaults(self) -> None:
        if not uvc_available():
            return
        device_index = self._device_index_getter()
        ok, msg = reset_uvc_controls(device_index)
        if ok:
            self.refresh_from_device()
            self._status.setText("UVC controls reset to defaults.")
        else:
            self._status.setText(f"UVC reset failed: {msg}")
