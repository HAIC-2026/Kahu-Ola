#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – fail closed on missing build inputs.

data/raw/ is gitignored, so a fresh clone has none of it. A build step that silently used an
empty layer instead (no tsunami zones, no sirens, no care facilities) would write a bundle
that looks complete but is wrong. Every required input is therefore read through these
helpers: a missing or empty file raises MissingInput, which stops the build with a message
that names the file and how to get it. Steps with a documented, visible fallback (the
committed ArcGIS and State layer summaries; the area method when 2020 blocks are missing)
say so where they fall back; nothing else does.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HINT = ("Download it on a machine with internet access (python3 scripts/fetch_data.py and the "
        "other fetch_*.py scripts) or copy data/raw/ from Long. To refresh only the app "
        "(service worker VERSION, PDF copies) without data/raw/, run "
        "python3 scripts/build_app_data.py --copy-only; it reuses the committed bundle.")


class MissingInput(RuntimeError):
    """A required build input is missing or empty; the build stops."""


def rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def fail(path: Path, what: str, problem: str) -> MissingInput:
    return MissingInput(f"Build stopped: {what} ({rel(path)}) is {problem}. {HINT}")


def require(path: Path, what: str) -> Path:
    """The file exists and is not empty."""
    path = Path(path)
    if not path.is_file():
        raise fail(path, what, "missing")
    if path.stat().st_size == 0:
        raise fail(path, what, "empty")
    return path


def load_json(path: Path, what: str):
    """Parsed JSON; an empty object or list counts as missing."""
    data = json.loads(require(path, what).read_text(encoding="utf-8"))
    if not data:
        raise fail(path, what, "empty")
    return data


def load_geojson(path: Path, what: str, allow_empty: bool = False) -> dict:
    """A FeatureCollection with at least one feature (unless allow_empty)."""
    data = load_json(path, what)
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise fail(path, what, "not a GeoJSON FeatureCollection")
    if not data["features"] and not allow_empty:
        raise fail(path, what, "empty (no features)")
    return data


def require_all_or_none(folder: Path, names, what: str) -> bool:
    """True when every file is present (and non-empty), False when none is (the caller's
    documented fallback). A partial set raises: it means an interrupted download."""
    present = [n for n in names if (Path(folder) / n).exists()]
    if not present:
        return False
    for n in names:
        require(Path(folder) / n, f"{what}: {n}")
    return True
