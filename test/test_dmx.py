from marimapper.dmx.enttec_output import EnttecProOutput
from marimapper.dmx.generic_usb_output import GenericUsbOutput, build_ftdi_url
from marimapper.dmx.fixture_map import apply_fixture, universe_count_for_fixtures
from pyftdi.ftdi import Ftdi


def test_apply_fixture():
    channels = [0] * 16
    apply_fixture(channels, 2, 4, True, base_channel=0)
    assert channels[8:12] == [255, 255, 255, 255]
    assert channels[0] == 0


def test_universe_count():
    assert universe_count_for_fixtures(100, 4) == 1
    assert universe_count_for_fixtures(200, 4) == 2


def test_enttec_packet_format():
    output = EnttecProOutput(channels=4)
    output.set_all(128)
    packet = output.build_packet()
    assert packet[0] == 0x7E
    assert packet[1] == 6
    assert packet[-1] == 0xE7
    assert packet[5:9] == bytes([128, 128, 128, 128])


def test_generic_usb_frame_format():
    output = GenericUsbOutput(channels=24)
    output.set_channel(1, 10)
    output.set_channel(4, 200)
    frame = output.build_frame()
    assert frame[0] == 0
    assert frame[1] == 10
    assert frame[4] == 200
    assert len(frame) == 25  # start code + min 24 channels (ofxGenericDmx)


def test_build_ftdi_url():
    devices = Ftdi.list_devices()
    if not devices:
        return
    descriptor, interface = devices[0]
    url = build_ftdi_url(descriptor, interface)
    assert url.startswith("ftdi://ftdi:")
