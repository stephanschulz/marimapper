import argparse

from marimapper.dmx.scanner_factory import generic_usb_detection_factory


def generic_usb_set_args(parser):
    parser.add_argument(
        "--url",
        default=None,
        help="pyftdi URL (e.g. ftdi://ftdi:232:SERIAL/1) — auto-detect if omitted",
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


def generic_usb_backend_factory(args: argparse.Namespace):
    return generic_usb_detection_factory(args)
