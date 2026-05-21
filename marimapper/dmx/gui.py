#!/usr/bin/env python3
"""PySide6 DMX tester and camera LED detection (Art-Net / Enttec / Generic USB)."""

from __future__ import annotations

import json
import math
import os
import sys
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from marimapper.dmx.artnet_output import ArtnetOutput
from marimapper.dmx.detection_backend import DmxDetectionBackend
from marimapper.dmx.detection_config import DetectionDmxConfig
from marimapper.dmx.camera_window import CameraDetectionWindow
from marimapper.dmx.enttec_output import EnttecProOutput, list_serial_ports
from marimapper.dmx.generic_usb_output import GenericUsbOutput, list_ftdi_devices

SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "dmx_gui_settings.json"
)

DEVICE_ARTNET = "Art-Net"
DEVICE_ENTTEC = "Enttec USB Pro"
DEVICE_GENERIC = "Generic USB"


class ChannelVisualizer(QWidget):
    def __init__(self):
        super().__init__()
        self.data = bytearray(512)
        self.setMinimumHeight(120)
        self.setMinimumWidth(400)

    def set_data(self, data):
        self.data = bytearray(data)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        width = self.width()
        height = self.height()
        painter.fillRect(0, 0, width, height, QColor(20, 20, 20))

        bar_w = max(1, width / 512)
        for index in range(512):
            value = self.data[index]
            bar_h = (value / 255.0) * (height - 20)
            x = index * width / 512
            green = int(value * 0.8)
            color = (
                QColor(value, 200 + int(value * 0.2), green)
                if value > 0
                else QColor(30, 30, 30)
            )
            painter.fillRect(
                int(x), int(height - 10 - bar_h), max(1, int(bar_w)), int(bar_h), color
            )

        painter.setPen(QPen(QColor(80, 80, 80), 1))
        for frac in [0.25, 0.5, 0.75]:
            y = int(height - 10 - frac * (height - 20))
            painter.drawLine(0, y, width, y)

        painter.setPen(QColor(150, 150, 150))
        painter.setFont(QFont("Menlo", 9))
        for channel in range(0, 512, 64):
            x = int(channel * width / 512)
            painter.drawText(x + 2, height - 1, str(channel))

        painter.setPen(QColor(200, 200, 200))
        painter.drawText(4, 12, "255")
        painter.drawText(4, int(height - 10 - 0.5 * (height - 20)) + 4, "128")
        painter.drawText(4, height - 12, "0")
        painter.end()


class DmxControllerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MariMapper DMX + Detection")
        self.setMinimumWidth(520)

        self.device_mode = DEVICE_ARTNET
        self.artnet = ArtnetOutput()
        self.enttec = EnttecProOutput()
        self.generic_usb = GenericUsbOutput()
        self.running = False
        self.mode = "off"
        self.start_time = 0.0
        self.last_packet = bytearray(512)

        self.chase_active = False
        self.chase_pos = 0
        self.chase_last_time = 0.0
        self.chase_overlay: dict[int, int] = {}
        self._pending_port: str | None = None
        self.camera_window: CameraDetectionWindow | None = None
        self._camera_settings_pending: dict | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(8)

        device_group = QGroupBox("Output device")
        device_form = QFormLayout(device_group)
        self.device_combo = QComboBox()
        self.device_combo.addItems([DEVICE_ARTNET, DEVICE_ENTTEC, DEVICE_GENERIC])
        self.device_combo.currentTextChanged.connect(self.on_device_changed)
        device_form.addRow("Type:", self.device_combo)

        self.port_combo = QComboBox()
        self.port_refresh = QPushButton("Refresh ports")
        self.port_refresh.clicked.connect(self.refresh_ports)
        port_row = QHBoxLayout()
        port_row.addWidget(self.port_combo)
        port_row.addWidget(self.port_refresh)
        port_widget = QWidget()
        port_widget.setLayout(port_row)
        self.port_label = QLabel("Device:")
        device_form.addRow(self.port_label, port_widget)
        layout.addWidget(device_group)

        net_group = QGroupBox("Network (Art-Net)")
        net_form = QFormLayout(net_group)
        self.net_group = net_group
        self.ip_edit = QLineEdit("192.168.1.255")
        net_form.addRow("Target IP:", self.ip_edit)
        self.artsync_check = QCheckBox("Use ArtSync (synchronized output)")
        self.artsync_check.setToolTip(
            "Send one ArtSync after all universe DMX packets each frame."
        )
        net_form.addRow("", self.artsync_check)
        layout.addWidget(net_group)

        uni_group = QGroupBox("Universes (Art-Net)")
        self.uni_group = uni_group
        uni_layout = QHBoxLayout(uni_group)
        uni_layout.addWidget(QLabel("Start:"))
        self.uni_start = QSpinBox()
        self.uni_start.setRange(0, 300)
        self.uni_start.setValue(0)
        uni_layout.addWidget(self.uni_start)
        uni_layout.addWidget(QLabel("End:"))
        self.uni_end = QSpinBox()
        self.uni_end.setRange(0, 300)
        self.uni_end.setValue(0)
        uni_layout.addWidget(self.uni_end)
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.clicked.connect(self.rebuild_output)
        uni_layout.addWidget(self.btn_apply)
        layout.addWidget(uni_group)

        self.status_label = QLabel("Not connected")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(QFont("Menlo", 11))
        layout.addWidget(self.status_label)

        viz_group = QGroupBox("Channel output (preview)")
        viz_layout = QVBoxLayout(viz_group)
        self.visualizer = ChannelVisualizer()
        viz_layout.addWidget(self.visualizer)
        layout.addWidget(viz_group)

        det_group = QGroupBox("LED detection (DMX mapping)")
        det_form = QFormLayout(det_group)

        ch_row = QHBoxLayout()
        self.det_min_channel = QSpinBox()
        self.det_min_channel.setRange(1, 512)
        self.det_min_channel.setValue(1)
        ch_row.addWidget(self.det_min_channel)
        ch_row.addWidget(QLabel("to"))
        self.det_max_channel = QSpinBox()
        self.det_max_channel.setRange(1, 512)
        self.det_max_channel.setValue(50)
        ch_row.addWidget(self.det_max_channel)
        det_form.addRow("DMX channels:", ch_row)

        self.det_universe = QSpinBox()
        self.det_universe.setRange(0, 300)
        self.det_universe.setValue(0)
        self.det_universe_label = QLabel("Universe (Art-Net):")
        det_form.addRow(self.det_universe_label, self.det_universe)

        self.det_channels_per_fixture = QSpinBox()
        self.det_channels_per_fixture.setRange(1, 64)
        self.det_channels_per_fixture.setValue(1)
        det_form.addRow("Channels / bulb:", self.det_channels_per_fixture)

        self.det_on_level = QSpinBox()
        self.det_on_level.setRange(0, 255)
        self.det_on_level.setValue(255)
        det_form.addRow("DMX on level:", self.det_on_level)
        for widget in (
            self.det_min_channel,
            self.det_max_channel,
            self.det_channels_per_fixture,
            self.det_on_level,
        ):
            widget.valueChanged.connect(self._on_detection_mapping_changed)

        layout.addWidget(det_group)

        static_group = QGroupBox("Static")
        static_layout = QHBoxLayout(static_group)
        self.btn_all_on = QPushButton("All ON (255)")
        self.btn_all_on.clicked.connect(lambda: self.set_static(255))
        static_layout.addWidget(self.btn_all_on)
        self.btn_all_off = QPushButton("All OFF (0)")
        self.btn_all_off.clicked.connect(lambda: self.set_static(0))
        static_layout.addWidget(self.btn_all_off)
        layout.addWidget(static_group)

        slider_group = QGroupBox("Manual level")
        sl_row = QHBoxLayout(slider_group)
        self.level_slider = QSlider(Qt.Horizontal)
        self.level_slider.setRange(0, 255)
        self.level_slider.setValue(0)
        self.level_slider.valueChanged.connect(self.on_slider_changed)
        sl_row.addWidget(self.level_slider)
        self.level_label = QLabel("0")
        self.level_label.setMinimumWidth(35)
        self.level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sl_row.addWidget(self.level_label)
        layout.addWidget(slider_group)

        anim_group = QGroupBox("Animations")
        anim_layout = QVBoxLayout(anim_group)
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Duration (s):"))
        self.fade_duration = QDoubleSpinBox()
        self.fade_duration.setRange(0.1, 30.0)
        self.fade_duration.setValue(3.0)
        self.fade_duration.setSingleStep(0.5)
        speed_row.addWidget(self.fade_duration)
        anim_layout.addLayout(speed_row)

        brightness_row = QHBoxLayout()
        brightness_row.addWidget(QLabel("Min:"))
        self.brightness_min_slider = QSlider(Qt.Horizontal)
        self.brightness_min_slider.setRange(0, 255)
        self.brightness_min_slider.setValue(0)
        brightness_row.addWidget(self.brightness_min_slider)
        self.brightness_min_label = QLabel("0")
        self.brightness_min_label.setMinimumWidth(30)
        self.brightness_min_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.brightness_min_slider.valueChanged.connect(
            lambda value: self.brightness_min_label.setText(str(value))
        )
        brightness_row.addWidget(self.brightness_min_label)
        brightness_row.addWidget(QLabel("Max:"))
        self.brightness_max_slider = QSlider(Qt.Horizontal)
        self.brightness_max_slider.setRange(0, 255)
        self.brightness_max_slider.setValue(255)
        brightness_row.addWidget(self.brightness_max_slider)
        self.brightness_max_label = QLabel("255")
        self.brightness_max_label.setMinimumWidth(30)
        self.brightness_max_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.brightness_max_slider.valueChanged.connect(
            lambda value: self.brightness_max_label.setText(str(value))
        )
        brightness_row.addWidget(self.brightness_max_label)
        anim_layout.addLayout(brightness_row)

        offset_row = QHBoxLayout()
        offset_row.addWidget(QLabel("Universe offset:"))
        self.offset_slider = QSlider(Qt.Horizontal)
        self.offset_slider.setRange(0, 100)
        self.offset_slider.setValue(0)
        offset_row.addWidget(self.offset_slider)
        self.offset_label = QLabel("0.00")
        self.offset_label.setMinimumWidth(35)
        self.offset_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.offset_slider.valueChanged.connect(
            lambda value: self.offset_label.setText(f"{value / 100:.2f}")
        )
        offset_row.addWidget(self.offset_label)
        anim_layout.addLayout(offset_row)

        btn_row = QHBoxLayout()
        self.btn_fade = QPushButton("Fade Up/Down")
        self.btn_fade.setCheckable(True)
        self.btn_fade.clicked.connect(lambda checked: self.toggle_mode("fade", checked))
        btn_row.addWidget(self.btn_fade)
        self.btn_sine = QPushButton("Sine Wave")
        self.btn_sine.setCheckable(True)
        self.btn_sine.clicked.connect(lambda checked: self.toggle_mode("sine", checked))
        btn_row.addWidget(self.btn_sine)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.clicked.connect(self.stop_animation)
        btn_row.addWidget(self.btn_stop)
        anim_layout.addLayout(btn_row)
        layout.addWidget(anim_group)

        chase_group = QGroupBox("Chase")
        chase_layout = QVBoxLayout(chase_group)
        self.btn_chase = QPushButton("Chase ON")
        self.btn_chase.setCheckable(True)
        self.btn_chase.clicked.connect(self.toggle_chase)
        chase_layout.addWidget(self.btn_chase)

        ch_range_row = QHBoxLayout()
        ch_range_row.addWidget(QLabel("Start ch:"))
        self.chase_ch_start = QSpinBox()
        self.chase_ch_start.setRange(0, 511)
        self.chase_ch_start.setValue(0)
        ch_range_row.addWidget(self.chase_ch_start)
        ch_range_row.addWidget(QLabel("End ch:"))
        self.chase_ch_end = QSpinBox()
        self.chase_ch_end.setRange(0, 511)
        self.chase_ch_end.setValue(511)
        ch_range_row.addWidget(self.chase_ch_end)
        chase_layout.addLayout(ch_range_row)

        chase_speed_row = QHBoxLayout()
        chase_speed_row.addWidget(QLabel("Speed:"))
        self.chase_speed_slider = QSlider(Qt.Horizontal)
        self.chase_speed_slider.setRange(0, 100)
        self.chase_speed_slider.setValue(50)
        self.chase_speed_slider.setInvertedAppearance(True)
        chase_speed_row.addWidget(self.chase_speed_slider)
        self.chase_speed_label = QLabel("")
        self.chase_speed_label.setMinimumWidth(50)
        self.chase_speed_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.chase_speed_slider.valueChanged.connect(
            lambda value: self.chase_speed_label.setText(f"{self._chase_ms(value)}ms")
        )
        chase_speed_row.addWidget(self.chase_speed_label)
        chase_layout.addLayout(chase_speed_row)
        self.chase_speed_label.setText(f"{self._chase_ms(50)}ms")

        chase_opts_row = QHBoxLayout()
        chase_opts_row.addWidget(QLabel("Level:"))
        self.chase_level = QSpinBox()
        self.chase_level.setRange(0, 255)
        self.chase_level.setValue(255)
        chase_opts_row.addWidget(self.chase_level)
        chase_opts_row.addWidget(QLabel("Trail:"))
        self.chase_trail = QSpinBox()
        self.chase_trail.setRange(0, 100)
        self.chase_trail.setValue(0)
        chase_opts_row.addWidget(self.chase_trail)
        chase_opts_row.addWidget(QLabel("Step:"))
        self.chase_step = QSpinBox()
        self.chase_step.setRange(1, 64)
        self.chase_step.setValue(1)
        chase_opts_row.addWidget(self.chase_step)
        chase_layout.addLayout(chase_opts_row)
        layout.addWidget(chase_group)

        self.timer = QTimer()
        self.timer.setInterval(25)
        self.timer.timeout.connect(self.tick)

        self.chase_timer = QTimer()
        self.chase_timer.setInterval(16)
        self.chase_timer.timeout.connect(self.chase_tick)

        self.viz_timer = QTimer()
        self.viz_timer.setInterval(50)
        self.viz_timer.timeout.connect(self.update_viz)
        self.viz_timer.start()

        self.artsync_check.toggled.connect(lambda _: self.rebuild_output())
        self.load_settings()
        self.show_camera_window()
        self.on_device_changed(self.device_combo.currentText())

    def on_device_changed(self, device: str):
        self.device_mode = device
        is_artnet = device == DEVICE_ARTNET
        self.net_group.setVisible(is_artnet)
        self.uni_group.setVisible(is_artnet)
        self.port_label.setVisible(not is_artnet)
        self.port_combo.setVisible(not is_artnet)
        self.port_refresh.setVisible(not is_artnet)
        self.offset_slider.setEnabled(is_artnet)
        self.port_label.setText(
            "FTDI device:" if device == DEVICE_GENERIC else "Serial port:"
        )
        show_uni = device == DEVICE_ARTNET
        self.det_universe_label.setVisible(show_uni)
        self.det_universe.setVisible(show_uni)
        self.refresh_ports()
        if self._pending_port:
            port_index = self.port_combo.findData(self._pending_port)
            if port_index >= 0:
                self.port_combo.setCurrentIndex(port_index)
            self._pending_port = None
        self.rebuild_output()

    def refresh_ports(self):
        self.port_combo.clear()
        if self.device_mode == DEVICE_GENERIC:
            for url, label in list_ftdi_devices():
                self.port_combo.addItem(label, url)
        else:
            for device, description in list_serial_ports():
                label = f"{device} — {description}" if description else device
                self.port_combo.addItem(label, device)

    def universe_count(self) -> int:
        if self.device_mode in (DEVICE_ENTTEC, DEVICE_GENERIC):
            return 1
        return max(1, self.artnet.universe_count)

    def rebuild_output(self):
        if self.device_mode == DEVICE_ARTNET:
            self.enttec.disconnect()
            self.generic_usb.disconnect()
            self.artnet.target_ip = self.ip_edit.text()
            self.artnet.universe_start = self.uni_start.value()
            self.artnet.universe_end = self.uni_end.value()
            self.artnet.use_artsync = self.artsync_check.isChecked()
            count = self.artnet.rebuild()
            self.running = count > 0
            self.status_label.setText(
                f"Art-Net: {count} universes ({self.uni_start.value()}–{self.uni_end.value()}) → {self.ip_edit.text()}"
            )
        elif self.device_mode == DEVICE_ENTTEC:
            self.artnet.stop()
            self.generic_usb.disconnect()
            port = self.port_combo.currentData()
            if port is None and self.port_combo.count():
                port = self.port_combo.itemData(0)
            connected = self.enttec.connect(port)
            self.running = connected
            if connected:
                self.status_label.setText(f"Enttec: {self.enttec.device_name} @ 57600")
            else:
                self.status_label.setText("Enttec: no device connected (check USB)")
        else:
            self.artnet.stop()
            self.enttec.disconnect()
            url = self.port_combo.currentData()
            if url is None and self.port_combo.count():
                url = self.port_combo.itemData(0)
            connected = self.generic_usb.connect(url)
            self.running = connected
            if connected:
                self.status_label.setText(
                    f"Generic USB: {self.generic_usb.device_name} @ 250000 (FTDI raw DMX)"
                )
            else:
                self.status_label.setText(
                    "Generic USB: no FTDI device (install pyftdi; avoid VCP driver conflict)"
                )

    def send_all_packets(self, packets: list[bytearray]):
        if not self.running:
            return

        if self.chase_active:
            ch_start = self.chase_ch_start.value()
            ch_end = self.chase_ch_end.value()
            if ch_end < ch_start:
                ch_start, ch_end = ch_end, ch_start
            overlay = self.chase_overlay
            for packet in packets:
                for channel in range(ch_start, ch_end + 1):
                    packet[channel] = overlay.get(channel, 0)

        self.last_packet = bytearray(packets[0]) if packets else bytearray(512)

        if self.device_mode == DEVICE_ARTNET:
            err_count = self.artnet.send_packets(packets)
            if err_count > 0:
                self.status_label.setText(
                    f"Send errors: {err_count}/{self.artnet.universe_count}"
                )
        elif self.device_mode == DEVICE_ENTTEC:
            try:
                self.enttec.set_frame(packets[0])
                self.enttec.send()
            except OSError as error:
                self.status_label.setText(f"Enttec send error: {error}")
        else:
            try:
                self.generic_usb.set_frame(packets[0])
                self.generic_usb.send()
            except OSError as error:
                self.status_label.setText(f"Generic USB send error: {error}")

    def update_viz(self):
        self.visualizer.set_data(self.last_packet)

    def _get_offset_amount(self) -> float:
        return self.offset_slider.value() / 100.0

    def _map_brightness(self, normalized: float) -> int:
        lo = self.brightness_min_slider.value()
        hi = self.brightness_max_slider.value()
        if lo > hi:
            lo, hi = hi, lo
        return int(lo + normalized * (hi - lo))

    @staticmethod
    def _chase_ms(slider_val: int) -> int:
        return int(5 * (400 ** (slider_val / 100.0)))

    def set_static(self, level: int):
        self.stop_animation()
        self.level_slider.setValue(level)
        packets = self._level_packets(level)
        self.send_all_packets(packets)

    def on_slider_changed(self, value: int):
        self.level_label.setText(str(value))
        if self.mode == "off":
            self.send_all_packets(self._level_packets(value))

    def _level_packets(self, value: int) -> list[bytearray]:
        count = self.universe_count()
        amount = self._get_offset_amount()
        packets = []
        for index in range(count):
            offset = int((index / count) * 255 * amount)
            val = (value + offset) % 256
            packets.append(bytearray([val] * 512))
        return packets

    def toggle_mode(self, mode: str, checked: bool):
        if checked:
            self.mode = mode
            self.start_time = time.monotonic()
            self.btn_fade.setChecked(mode == "fade")
            self.btn_sine.setChecked(mode == "sine")
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.stop_animation()

    def stop_animation(self):
        self.mode = "off"
        self.timer.stop()
        self.btn_fade.setChecked(False)
        self.btn_sine.setChecked(False)

    def tick(self):
        elapsed = time.monotonic() - self.start_time
        duration = self.fade_duration.value()
        count = self.universe_count()
        amount = self._get_offset_amount()

        if self.mode == "fade":
            packets = []
            for index in range(count):
                uni_offset = (index / count) * math.pi * 2 * amount
                phase = ((elapsed + uni_offset * duration / (math.pi * 2)) % (duration * 2)) / duration
                if phase > 1.0:
                    phase = 2.0 - phase
                norm = math.sin(phase * math.pi - math.pi / 2) * 0.5 + 0.5
                level = self._map_brightness(norm)
                packets.append(bytearray([level] * 512))
            self.level_slider.blockSignals(True)
            self.level_slider.setValue(packets[0][0])
            self.level_slider.blockSignals(False)
            self.level_label.setText(str(packets[0][0]))
            self.send_all_packets(packets)

        elif self.mode == "sine":
            packets = []
            for index in range(count):
                packet = bytearray(512)
                uni_phase_offset = (index / count) * math.pi * 2 * amount
                for channel in range(512):
                    phase = (
                        (channel / 512.0) * math.pi * 2
                        + (elapsed / duration) * math.pi * 2
                        + uni_phase_offset
                    )
                    norm = math.sin(phase) * 0.5 + 0.5
                    packet[channel] = self._map_brightness(norm)
                packets.append(packet)
            self.send_all_packets(packets)

    def toggle_chase(self, checked: bool):
        self.chase_active = checked
        if checked:
            self.btn_chase.setText("Chase ON")
            self.chase_pos = self.chase_ch_start.value()
            self.chase_last_time = time.monotonic()
            if not self.chase_timer.isActive():
                self.chase_timer.start()
        else:
            self.btn_chase.setText("Chase OFF")
            self.chase_timer.stop()

    def chase_tick(self):
        if not self.chase_active or not self.running:
            return
        now = time.monotonic()
        interval = self._chase_ms(self.chase_speed_slider.value()) / 1000.0
        if now - self.chase_last_time < interval:
            return
        self.chase_last_time = now

        ch_start = self.chase_ch_start.value()
        ch_end = self.chase_ch_end.value()
        if ch_end < ch_start:
            ch_start, ch_end = ch_end, ch_start
        ch_range = ch_end - ch_start + 1

        level = self.chase_level.value()
        trail = self.chase_trail.value()
        step = self.chase_step.value()

        self.chase_overlay = {}
        self.chase_overlay[self.chase_pos] = level
        for trail_index in range(1, trail + 1):
            trail_ch = ch_start + (self.chase_pos - ch_start - trail_index * step) % ch_range
            intensity = 1.0 - (trail_index / (trail + 1))
            self.chase_overlay[trail_ch] = int(level * intensity)

        self.chase_pos += step
        if self.chase_pos > ch_end:
            self.chase_pos = ch_start

        if self.mode == "off" and not self.timer.isActive():
            self.send_all_packets(self._level_packets(self.level_slider.value()))

    def get_detection_config(self) -> DetectionDmxConfig:
        return DetectionDmxConfig(
            min_channel=self.det_min_channel.value(),
            max_channel=self.det_max_channel.value(),
            channels_per_fixture=self.det_channels_per_fixture.value(),
            universe=self.det_universe.value(),
            on_level=self.det_on_level.value(),
            burst_count=3,
        )

    def prepare_artnet_for_detection(self) -> None:
        """Single-universe Art-Net for detection scans."""
        self.artnet.target_ip = self.ip_edit.text()
        universe = self.det_universe.value()
        self.artnet.universe_start = universe
        self.artnet.universe_end = universe
        self.artnet.use_artsync = self.artsync_check.isChecked()
        self.artnet.rebuild()
        self.running = self.artnet.universe_count > 0

    def build_detection_backend(self) -> DmxDetectionBackend:
        if not self.running:
            self.rebuild_output()
        if self.device_mode == DEVICE_ARTNET:
            self.prepare_artnet_for_detection()
        config = self.get_detection_config()
        return DmxDetectionBackend(
            self.device_mode,
            config,
            artnet=self.artnet if self.device_mode == DEVICE_ARTNET else None,
            enttec=self.enttec if self.device_mode == DEVICE_ENTTEC else None,
            generic_usb=self.generic_usb if self.device_mode == DEVICE_GENERIC else None,
        )

    def _on_detection_mapping_changed(self, *_args) -> None:
        if self.camera_window is not None and self.camera_window.isVisible():
            self.camera_window._sync_led_index_range()
            self.camera_window._on_led_index_changed(
                self.camera_window.det_current_id.value()
            )

    def detection_fixture_count(self) -> int:
        return self.build_detection_backend().get_led_count()

    def highlight_detection_led(self, led_index: int) -> tuple[int, int]:
        """
        Set DMX on_level on the given LED fixture and 0 on all other channels.

        Returns (first DMX channel, 1-based) and the level sent.
        """
        backend = self.build_detection_backend()
        count = backend.get_led_count()
        if led_index < 0 or led_index >= count:
            raise ValueError(f"LED index {led_index} out of range 0–{count - 1}")
        backend.set_led(led_index, True)
        config = backend.config
        dmx_ch = config.min_channel + led_index * config.channels_per_fixture
        return dmx_ch, config.on_level

    def show_camera_window(self) -> None:
        if self.camera_window is None:
            self.camera_window = CameraDetectionWindow(self)
            if self._camera_settings_pending is not None:
                self.camera_window.apply_settings(self._camera_settings_pending)
                self._camera_settings_pending = None
        self.camera_window.show()
        self.camera_window.raise_()
        self.camera_window.activateWindow()

    def save_settings(self):
        settings = {
            "device": self.device_combo.currentText(),
            "port_or_url": self.port_combo.currentData(),
            "ip": self.ip_edit.text(),
            "artsync": self.artsync_check.isChecked(),
            "uni_start": self.uni_start.value(),
            "uni_end": self.uni_end.value(),
            "level": self.level_slider.value(),
            "fade_duration": self.fade_duration.value(),
            "brightness_min": self.brightness_min_slider.value(),
            "brightness_max": self.brightness_max_slider.value(),
            "offset": self.offset_slider.value(),
            "chase_ch_start": self.chase_ch_start.value(),
            "chase_ch_end": self.chase_ch_end.value(),
            "chase_speed": self.chase_speed_slider.value(),
            "chase_level": self.chase_level.value(),
            "chase_trail": self.chase_trail.value(),
            "chase_step": self.chase_step.value(),
            "det_min_channel": self.det_min_channel.value(),
            "det_max_channel": self.det_max_channel.value(),
            "det_universe": self.det_universe.value(),
            "det_channels_per_fixture": self.det_channels_per_fixture.value(),
            "det_on_level": self.det_on_level.value(),
        }
        if self.camera_window is not None:
            settings.update(self.camera_window.settings_snapshot())
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as handle:
                json.dump(settings, handle, indent=2)
        except OSError:
            pass

    def load_settings(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as handle:
                settings = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return

        device = settings.get("device", DEVICE_ARTNET)
        index = self.device_combo.findText(device)
        if index >= 0:
            self.device_combo.setCurrentIndex(index)

        self._pending_port = settings.get("port_or_url", settings.get("serial_port"))

        self.ip_edit.setText(settings.get("ip", "192.168.1.255"))
        self.artsync_check.setChecked(settings.get("artsync", False))
        self.uni_start.setValue(settings.get("uni_start", 0))
        self.uni_end.setValue(settings.get("uni_end", 0))
        self.level_slider.setValue(settings.get("level", 0))
        self.fade_duration.setValue(settings.get("fade_duration", 3.0))
        self.brightness_min_slider.setValue(settings.get("brightness_min", 0))
        self.brightness_max_slider.setValue(settings.get("brightness_max", 255))
        self.offset_slider.setValue(settings.get("offset", 0))
        self.chase_ch_start.setValue(settings.get("chase_ch_start", 0))
        self.chase_ch_end.setValue(settings.get("chase_ch_end", 511))
        self.chase_speed_slider.setValue(settings.get("chase_speed", 50))
        self.chase_level.setValue(settings.get("chase_level", 255))
        self.chase_trail.setValue(settings.get("chase_trail", 0))
        self.chase_step.setValue(settings.get("chase_step", 1))
        self.det_min_channel.setValue(settings.get("det_min_channel", 1))
        self.det_max_channel.setValue(settings.get("det_max_channel", 50))
        self.det_universe.setValue(settings.get("det_universe", 0))
        self.det_channels_per_fixture.setValue(
            settings.get("det_channels_per_fixture", 1)
        )
        self.det_on_level.setValue(settings.get("det_on_level", 255))
        if self.camera_window is not None:
            self.camera_window.apply_settings(settings)
        else:
            self._camera_settings_pending = settings

    def closeEvent(self, event):
        if self.camera_window is not None:
            self.camera_window.close()
        self.save_settings()
        self.timer.stop()
        self.chase_timer.stop()
        self.viz_timer.stop()
        self.artnet.stop()
        self.enttec.disconnect()
        self.generic_usb.disconnect()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = DmxControllerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
