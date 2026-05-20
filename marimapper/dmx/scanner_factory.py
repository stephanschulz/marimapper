"""Build DmxDetectionBackend for mariMapper CLI scans."""

from __future__ import annotations

import argparse
from functools import partial

from marimapper.dmx.artnet_output import ArtnetOutput
from marimapper.dmx.detection_backend import (
    DEVICE_ARTNET,
    DEVICE_ENTTEC,
    DEVICE_GENERIC,
    DmxDetectionBackend,
)
from marimapper.dmx.detection_config import DetectionDmxConfig
from marimapper.dmx.enttec_output import EnttecProOutput
from marimapper.dmx.generic_usb_output import GenericUsbOutput


def _detection_config_from_args(args: argparse.Namespace) -> DetectionDmxConfig:
    return DetectionDmxConfig(
        min_channel=args.det_min_channel,
        max_channel=args.det_max_channel,
        channels_per_fixture=args.det_channels_per_fixture,
        universe=args.det_universe,
        on_level=args.det_on_level,
        burst_count=getattr(args, "burst_count", 3),
    )


def artnet_detection_factory(args: argparse.Namespace):
    config = _detection_config_from_args(args)

    def factory():
        output = ArtnetOutput(
            target_ip=args.server,
            universe_start=config.universe,
            universe_end=config.universe,
            use_artsync=args.artsync,
        )
        output.rebuild()
        return DmxDetectionBackend(DEVICE_ARTNET, config, artnet=output)

    return factory


def enttec_detection_factory(args: argparse.Namespace):
    config = _detection_config_from_args(args)

    def factory():
        output = EnttecProOutput(port=args.port)
        if not output.connect(args.port):
            raise RuntimeError("Failed to connect Enttec DMX USB Pro")
        return DmxDetectionBackend(DEVICE_ENTTEC, config, enttec=output)

    return factory


def generic_usb_detection_factory(args: argparse.Namespace):
    config = _detection_config_from_args(args)

    def factory():
        output = GenericUsbOutput(url=args.url)
        if not output.connect(args.url):
            raise RuntimeError("Failed to connect Generic USB DMX")
        return DmxDetectionBackend(DEVICE_GENERIC, config, generic_usb=output)

    return factory
