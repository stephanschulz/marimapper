from unittest.mock import MagicMock, patch

from marimapper.camera_uvc_mac import (
    apply_uvc_exposure,
    find_uvc_util,
    slider_to_uvc_exposure_fraction,
)


def test_slider_to_uvc_fraction():
    assert slider_to_uvc_exposure_fraction(-13) == 0.0
    assert slider_to_uvc_exposure_fraction(0) == 1.0


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
