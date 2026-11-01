"""Render a fixed set of app views in headless Chrome and return their visible text.

Used by tests/test_served_files.py to check that moving per-area computation to build time
did not change what anyone sees. The reference (tests/golden/views_before.json.gz) was
was first rendered before that change (commit fc9f627, PR #11) and is regenerated, keeping
the same views, whenever on-screen text changes on purpose:

    python3 tests/render_views.py --write

Views: the 20 plan views; area panels (two per county for tsunami and hurricane, the
smallest at-risk area and the first in the list, plus Kalawao, a small area); the four
stress-test views; what-if at plan defaults and with sliders moved; the Messages tab.
Only the data version line is masked (it changes with every build)."""
import functools
import gzip
import html
import http.server
import json
import re
import socket
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_playbooks as bp  # noqa: E402

APP = ROOT / "app"
GOLDEN = ROOT / "tests" / "golden" / "views_before.json.gz"
COUNTIES = ["Kauai", "Honolulu", "Maui", "Hawaii"]
HAZARDS = ["hurricane", "wildfire", "tsunami", "inland_flood", "coastal_flood"]
PANEL_AREAS = {  # (county, hazard) -> areas whose panel is compared (fixed when the reference was made)
}
WHATIF = ["county=Maui&hazard=wildfire", "county=Honolulu&hazard=hurricane", "county=Kauai&hazard=coastal_flood",
          "county=Hawaii&hazard=tsunami",
          "county=Maui&hazard=hurricane&rate=0.25&stay=7&cap=13-2078",
          "county=Honolulu&hazard=tsunami&rate=0.01",
          "county=Kauai&hazard=coastal_flood&rate=0.2&trip=4",
          "county=Hawaii&hazard=tsunami&outage=5&rate=0.08"]


def views(panels: list) -> dict:
    """name -> (query + hash, part): part 'page' = whole page, 'panel' = the area panel,
    'whatif' = the what-if results."""
    out = {}
    for c in COUNTIES:
        for h in HAZARDS:
            out[f"plan {c} {h}"] = (f"?county={c}&hazard={h}#plan", "page")
        out[f"stress {c}"] = (f"?county={c}&hazard=tsunami#stress", "page")
    for c, h, f in panels:
        out[f"panel {c} {h} {f}"] = (f"?county={c}&hazard={h}&area={f}#plan", "panel")
    for q in WHATIF:
        out[f"whatif {q}"] = (f"?{q}#whatif", "whatif")
    out["messages"] = ("?county=Maui&hazard=tsunami#messages", "page")
    return out


def visible(dom: str, part: str) -> str:
    if part == "panel":
        m = re.search(r'<section id="area-panel".*?</section>', dom, re.S)
        dom = m.group(0) if m else ""
    elif part == "whatif":
        m = re.search(r'<div id="wi-out">.*?</main>', dom, re.S)
        dom = m.group(0) if m else ""
    dom = re.sub(r"(?s)<(script|style|noscript)[^>]*>.*?</\1>", " ", dom)
    t = html.unescape(re.sub(r"<[^>]+>", " ", dom))
    return mask(normalize(t))


def normalize(t: str) -> str:
    """Collapse whitespace runs and drop a space before punctuation, so that wrapping a
    word in an element (keep(), nowrap) does not count as a text change."""
    t = " ".join(t.split())
    return re.sub(r" (?=[.,;:!?)\]])", "", t)


def mask(t: str) -> str:
    """The data version (a 12-character hash) changes with every build."""
    return re.sub(r"\b[0-9a-f]{12}\b", "VERSION", t)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def render(app: Path, todo: dict, browser: str | None = None) -> dict:
    browser = browser or bp.find_browser()
    port = free_port()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(app))
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=str(app))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def one(item):
        name, (q, part) = item
        with tempfile.TemporaryDirectory() as prof:
            dom = subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={prof}",
                                  "--virtual-time-budget=15000", "--dump-dom", f"http://127.0.0.1:{port}/{q}"],
                                 capture_output=True, text=True, timeout=240).stdout
        return name, visible(dom, part)
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            return dict(pool.map(one, sorted(todo.items())))
    finally:
        server.shutdown()


def pick_panels(bundle: dict) -> list:
    """Two areas per county for tsunami and hurricane (smallest at-risk above 0, and the
    largest), plus Kalawao (fewer than 100 residents)."""
    out = [("Maui", "hurricane", "15005031900")]
    for key, sc in sorted(bundle["scenarios"].items()):
        c, h = key.split("|")
        if h not in ("tsunami", "hurricane"):
            continue
        ranked = sorted(((v[0], f) for f, v in sc["tracts"].items() if v[0] > 0))
        for _v, f in (ranked[0], ranked[-1]):
            out.append((c, h, f))
    return out


def load_golden() -> dict:
    g = json.loads(gzip.decompress(GOLDEN.read_bytes()).decode("utf-8"))
    g["texts"] = {k: mask(normalize(v)) for k, v in g["texts"].items()}
    return g


if __name__ == "__main__":
    if "--write" in sys.argv:
        # the panel list is kept from the existing reference (the bundle no longer ships the
        # per-area values pick_panels() chose them by)
        panels = [tuple(x) for x in load_golden()["panels"]] if GOLDEN.exists() else \
            pick_panels(json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8")))
        texts = render(APP, views(panels))
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_bytes(gzip.compress(json.dumps({"panels": panels, "texts": texts}, ensure_ascii=False,
                                                    sort_keys=True).encode("utf-8"), mtime=0))
        print(f"wrote {GOLDEN.relative_to(ROOT)}: {len(texts)} views, {GOLDEN.stat().st_size // 1024} KB; "
              f"empty: {[k for k, v in texts.items() if len(v) < 50]}")
