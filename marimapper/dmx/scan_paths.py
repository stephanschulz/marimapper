"""Default directory for 2D scan CSVs, capture PNGs, and metadata."""

from __future__ import annotations

import shutil
from pathlib import Path

LEGACY_SCAN_DIR = Path.home() / "marimapper_maps"


def default_scan_dir() -> Path:
    """Project ``scans/`` folder (repo root, not user home)."""
    return Path(__file__).resolve().parents[2] / "scans"


def ensure_scan_dir() -> Path:
    path = default_scan_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def migrate_legacy_scans() -> int:
    """Move files from ``~/marimapper_maps`` into ``scans/``. Returns count moved."""
    target = ensure_scan_dir()
    if not LEGACY_SCAN_DIR.is_dir():
        return 0
    moved = 0
    for path in sorted(LEGACY_SCAN_DIR.iterdir()):
        if not path.is_file():
            continue
        dest = target / path.name
        if dest.exists():
            continue
        shutil.move(str(path), str(dest))
        moved += 1
    try:
        if not any(LEGACY_SCAN_DIR.iterdir()):
            LEGACY_SCAN_DIR.rmdir()
    except OSError:
        pass
    return moved
