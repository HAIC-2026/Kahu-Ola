#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – time a full rebuild from local data (metric 3).

Runs every offline build step in order, times the whole run, and writes
data/processed/rebuild_timing.json (seconds, steps, machine, Hawaiʻi date). The app's
Results section, the PDF playbooks and PLAN.md read the number from that file. Then
rebuilds the playbooks and the app bundle once more (not timed), so the PDFs and the app
show the same, newly recorded value.

Usage:  python3 scripts/time_rebuild.py
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hawaii_time import now_hst  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "processed" / "rebuild_timing.json"
STEPS = [
    ["fetch_data.py", "--offline"], ["build_map.py"], ["build_shelters.py"],
    ["build_languages_pums.py"], ["build_demographics.py", "--offline"],
    ["build_place_names.py", "--offline"], ["build_tract_labels.py", "--offline"],
    ["model_needs.py"], ["match.py"], ["build_playbooks.py"], ["build_app_data.py"],
]


def machine() -> str:
    if platform.system() == "Darwin":
        try:
            return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                  capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            pass
    return platform.processor() or platform.machine()


def main() -> int:
    t0 = time.perf_counter()
    for step in STEPS:
        subprocess.run([sys.executable, str(ROOT / "scripts" / step[0]), *step[1:]],
                       check=True, stdout=subprocess.DEVNULL)
    secs = round(time.perf_counter() - t0, 1)
    OUT.write_text(json.dumps({
        "seconds": secs, "steps": len(STEPS), "step_scripts": [s[0] for s in STEPS],
        "scenarios": len(json.loads((ROOT / "data" / "processed" / "needs_by_scenario.json")
                                    .read_text(encoding="utf-8"))["scenarios"]),
        "playbooks": len(list((ROOT / "playbooks").glob("*.pdf"))),
        "machine": machine(), "measured_at": now_hst(),
        "note": "Full rebuild from local data (no downloads), all build steps in order.",
    }, indent=1) + "\n", encoding="utf-8")
    for script in ("build_playbooks.py", "build_app_data.py"):     # same value in PDFs and app
        subprocess.run([sys.executable, str(ROOT / "scripts" / script)], check=True,
                       stdout=subprocess.DEVNULL)
    print(f"Full rebuild: {secs} s, {len(STEPS)} steps, on {machine()} -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
