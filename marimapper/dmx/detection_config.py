"""DMX channel mapping for camera LED identification."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DetectionDmxConfig:
    """Map scan LED indices to DMX channels (1-based min/max)."""

    min_channel: int = 1
    max_channel: int = 50
    channels_per_fixture: int = 1
    universe: int = 0
    on_level: int = 255
    burst_count: int = 3

    def validate(self) -> None:
        if self.min_channel < 1 or self.max_channel > 512:
            raise ValueError("DMX channels must be in range 1–512")
        if self.max_channel < self.min_channel:
            raise ValueError("max_channel must be >= min_channel")
        if self.channels_per_fixture < 1:
            raise ValueError("channels_per_fixture must be >= 1")

    def fixture_count(self) -> int:
        self.validate()
        span = self.max_channel - self.min_channel + 1
        if span % self.channels_per_fixture != 0:
            raise ValueError(
                f"Channel range {self.min_channel}–{self.max_channel} is not divisible "
                f"by channels_per_fixture ({self.channels_per_fixture})"
            )
        return span // self.channels_per_fixture

    def channel_for_led(self, led_index: int) -> int:
        """Return 0-based DMX index in a single universe buffer."""
        self.validate()
        if led_index < 0 or led_index >= self.fixture_count():
            raise IndexError(f"led_index {led_index} out of range")
        return (self.min_channel - 1) + led_index * self.channels_per_fixture
