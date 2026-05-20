import argparse

from marimapper.dmx.scanner_factory import enttec_detection_factory


def enttec_set_args(parser):
    parser.add_argument(
        "--port",
        default=None,
        help="Serial port (e.g. /dev/tty.usbserial-EN...) — auto-detect if omitted",
    )
    parser.add_argument("--fixture_count", default=160, type=int, help="Deprecated: use det_max_channel")
    parser.add_argument(
        "--channels_per_fixture", default=1, type=int, help="Deprecated: use det_channels_per_fixture"
    )
    parser.add_argument(
        "--start_channel",
        default=1,
        type=int,
        help="Deprecated: use det_min_channel",
    )
    parser.add_argument(
        "--burst_count",
        default=3,
        type=int,
        help="How many times to repeat each frame",
    )


def enttec_backend_factory(args: argparse.Namespace):
    return enttec_detection_factory(args)
