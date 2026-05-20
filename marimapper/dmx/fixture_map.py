"""Map marimapper LED indices to DMX channel buffers."""


def apply_fixture(
    channels: list[int],
    led_index: int,
    channels_per_fixture: int,
    on: bool,
    base_channel: int = 0,
) -> None:
    fixture_base = base_channel + led_index * channels_per_fixture
    value = 255 if on else 0
    for offset in range(channels_per_fixture):
        channel = fixture_base + offset
        if 0 <= channel < len(channels):
            channels[channel] = value


def universe_count_for_fixtures(fixture_count: int, channels_per_fixture: int) -> int:
    total_channels = fixture_count * channels_per_fixture
    return total_channels // 512 + (1 if total_channels % 512 else 0)
