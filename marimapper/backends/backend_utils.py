from marimapper.backends.custom import custom_backend
from marimapper.backends.dummy import dummy_backend
from marimapper.backends.fadecandy import fadecandy_backend
from marimapper.backends.fcmega import fcmega_backend
from marimapper.backends.pixelblaze import pixelblaze_backend
from marimapper.backends.wled import wled_backend
from marimapper.backends.artnet import artnet_backend
from marimapper.backends.enttec import enttec_backend
from marimapper.backends.generic_usb import generic_usb_backend

backend_factories = {
    "custom": custom_backend.custom_backend_factory,
    "dummy": dummy_backend.dummy_backend_factory,
    "fadecandy": fadecandy_backend.fadecandy_backend_factory,
    "fcmega": fcmega_backend.fcmega_backend_factory,
    "pixelblaze": pixelblaze_backend.pixelblaze_backend_factory,
    "wled": wled_backend.wled_backend_factory,
    "artnet": artnet_backend.artnet_backend_factory,
    "enttec": enttec_backend.enttec_backend_factory,
    "generic_usb": generic_usb_backend.generic_usb_backend_factory,
}

backend_arg_setters = {
    "custom": custom_backend.custom_backend_set_args,
    "dummy": dummy_backend.dummy_backend_set_args,
    "fadecandy": fadecandy_backend.fadecandy_backend_set_args,
    "fcmega": fcmega_backend.fcmega_backend_set_args,
    "pixelblaze": pixelblaze_backend.pixelblaze_backend_set_args,
    "wled": wled_backend.wled_backend_set_args,
    "artnet": artnet_backend.artnet_set_args,
    "enttec": enttec_backend.enttec_set_args,
    "generic_usb": generic_usb_backend.generic_usb_set_args,
}
