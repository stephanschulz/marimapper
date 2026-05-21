from marimapper.dmx.scan_paths import (
    default_scan_dir,
    migrate_legacy_scans,
)


def test_default_scan_dir_is_project_scans():
    path = default_scan_dir()
    assert path.name == "scans"
    assert path.parent.name == "pixel-mapper"


def test_migrate_legacy_scans(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy_maps"
    legacy.mkdir()
    csv_file = legacy / "led_map_2d_test.csv"
    csv_file.write_text("index,u,v\n0,0.1,0.2\n")
    png_file = legacy / "led_map_2d_test.png"
    png_file.write_bytes(b"png")

    target = tmp_path / "scans"
    monkeypatch.setattr("marimapper.dmx.scan_paths.LEGACY_SCAN_DIR", legacy)
    monkeypatch.setattr(
        "marimapper.dmx.scan_paths.default_scan_dir", lambda: target
    )

    moved = migrate_legacy_scans()
    assert moved == 2
    assert (target / "led_map_2d_test.csv").is_file()
    assert (target / "led_map_2d_test.png").is_file()
    assert not legacy.exists() or not list(legacy.iterdir())
