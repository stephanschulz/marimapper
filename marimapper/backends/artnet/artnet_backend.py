import argparse

from marimapper.dmx.scanner_factory import artnet_detection_factory


def artnet_set_args(parser):
    parser.add_argument("--fixture_count", default=160, type=int, help="Deprecated: use det_max_channel")
    parser.add_argument("--base_universe", default=0, type=int, help="Deprecated: use det_universe")
    parser.add_argument(
        "--channels_per_fixture", default=4, type=int, help="Deprecated: use det_channels_per_fixture"
    )
    parser.add_argument(
        "--server", default="255.255.255.255", help="The Art-Net target IP address"
    )
    parser.add_argument("--broadcast", action="store_true", help="Whether to broadcast")
    parser.add_argument(
        "--artsync",
        action="store_true",
        help="Send ArtSync after each frame (multi-universe sync)",
    )
    parser.add_argument(
        "--burst_count",
        default=5,
        type=int,
        help="How many times to repeat each DMX frame (some nodes need a stream)",
    )


def artnet_backend_factory(args: argparse.Namespace):
    return artnet_detection_factory(args)
