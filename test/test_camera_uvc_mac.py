from unittest.mock import MagicMock, patch

from marimapper.camera_uvc_mac import (
    apply_uvc_exposure,
    find_uvc_util,
    parse_uvc_show_control,
    slider_to_uvc_exposure_fraction,
)


FOCUS_SHOW = """focus-abs {
  type-description: {
    single value, unsigned 16-bit integer
  },
  minimum: 0
  maximum: 255
  step-size: 5
  default-value: 0
  current-value: 10
}"""

AUTO_FOCUS_SHOW = """auto-focus {
  type-description: {
    single value, boolean
  },
  minimum: false
  maximum: true
  default-value: true
  current-value: false
}"""


def test_slider_to_uvc_fraction():
    assert slider_to_uvc_exposure_fraction(-13) == 0.0
    assert slider_to_uvc_exposure_fraction(0) == 1.0


def test_parse_uvc_show_control_int():
    info = parse_uvc_show_control(FOCUS_SHOW, "focus-abs")
    assert info is not None
    assert info.kind == "int"
    assert info.minimum == 0
    assert info.maximum == 255
    assert info.current == 10


def test_parse_uvc_show_control_bool():
    info = parse_uvc_show_control(AUTO_FOCUS_SHOW, "auto-focus")
    assert info is not None
    assert info.kind == "bool"
    assert info.current is False


@patch("marimapper.camera_uvc_mac.ensure_uvc_util")
@patch("marimapper.camera_uvc_mac._run_uvc")
@patch("marimapper.camera_uvc_mac._select_args")
def test_apply_uvc_manual(mock_select, mock_run, mock_ensure):
    mock_ensure.return_value = MagicMock()
    mock_select.return_value = ["--select-by-vendor-and-product-id", "0x046d:0x085e"]
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    ok, msg = apply_uvc_exposure(-10, device_index=1, manual=True)
    assert ok
    assert "UVC manual" in msg
    args = mock_run.call_args[0][0]
    assert "auto-exposure-mode=1" in args
    assert any("exposure-time-abs=" in a for a in args)


@patch("marimapper.camera_uvc_mac._CACHE_BIN")
def test_find_uvc_util_prefers_cache(mock_cache, tmp_path):
    binary = tmp_path / "uvc-util"
    binary.write_text("#!/bin/sh\necho ok\n")
    binary.chmod(0o755)
    with patch("marimapper.camera_uvc_mac._uvc_util_candidates", return_value=[binary]):
        assert find_uvc_util() == binary
