"""Static SVG maps from tract polygons and site points. Pure Python, no dependencies.

Used by build_playbooks.py (printed maps) and build_app_data.py (simplified geometry for
the offline app). No basemap tiles, no web fonts, no network.
"""
from __future__ import annotations

import math
from html import escape

MAIN_ISLANDS_WEST = -160.6        # excludes the Northwestern Hawaiian Islands from extents

# Sequential single-hue ramp: lightness falls steadily, so classes stay distinct in
# black-and-white print (ColorBrewer Blues 5).
RAMP = ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"]
NOT_AT_RISK = "#ffffff"

# Site status -> (marker shape, label). Shape + label, never color alone.
MARKERS = {
    "ok": ("circle", "Usable site"),
    "check": ("triangle", "Check flood zone"),
    "check (tract-level)": ("triangle", "Check flood zone"),
    "undetermined": ("diamond", "Flood risk not mapped (FEMA zone D)"),
    "exclude": ("square", "Not for this hazard"),
}


def need_names(k: int) -> list:
    """Plain names for k color classes: 'Lowest need' ... 'Highest need'."""
    if k <= 1:
        return ["People with needs"]
    middle = {3: ["Middle"], 4: ["Lower", "Higher"], 5: ["Lower", "Middle", "Higher"]}
    return ["Lowest need"] + middle.get(k, ["Middle"] * (k - 2)) + ["Highest need"]


def rings(geom: dict) -> list:
    if not geom:
        return []
    if geom["type"] == "Polygon":
        return geom["coordinates"]
    if geom["type"] == "MultiPolygon":
        return [r for poly in geom["coordinates"] for r in poly]
    return []


def _perp(p, a, b) -> float:
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return math.hypot(x - x1, y - y1)
    return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / math.hypot(dx, dy)


def simplify(ring: list, tol: float) -> list:
    """Douglas-Peucker (iterative). Keeps closed rings closed and at least 4 points."""
    if len(ring) <= 4 or tol <= 0:
        return ring
    keep = [False] * len(ring)
    keep[0] = keep[-1] = True
    stack = [(0, len(ring) - 1)]
    while stack:
        i, j = stack.pop()
        best, idx = 0.0, None
        for k in range(i + 1, j):
            d = _perp(ring[k], ring[i], ring[j])
            if d > best:
                best, idx = d, k
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    out = [p for p, k in zip(ring, keep) if k]
    return out if len(out) >= 4 else ring


def extent(features: list) -> tuple:
    """(minx, miny, maxx, maxy) of the main-island parts of the features."""
    xs, ys = [], []
    for f in features:
        for r in rings(f.get("geometry")):
            for x, y in r:
                if x >= MAIN_ISLANDS_WEST:
                    xs.append(x)
                    ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else (-160.5, 18.8, -154.7, 22.3)


class Projection:
    """Equirectangular, scaled by cos(latitude), fitted into width x height."""

    def __init__(self, bbox: tuple, width: float, height: float, pad: float = 8):
        minx, miny, maxx, maxy = bbox
        self.k = math.cos(math.radians((miny + maxy) / 2))
        w = max((maxx - minx) * self.k, 1e-6)
        h = max(maxy - miny, 1e-6)
        self.s = min((width - 2 * pad) / w, (height - 2 * pad) / h)
        self.ox = pad + ((width - 2 * pad) - w * self.s) / 2
        self.oy = pad + ((height - 2 * pad) - h * self.s) / 2
        self.minx, self.maxy = minx, maxy

    def __call__(self, x: float, y: float) -> tuple:
        return (round(self.ox + (x - self.minx) * self.k * self.s, 1),
                round(self.oy + (self.maxy - y) * self.s, 1))


def path_d(geom: dict, proj: Projection, tol: float = 0.0) -> str:
    parts = []
    for r in rings(geom):
        if all(x < MAIN_ISLANDS_WEST for x, _ in r):
            continue
        pts = [proj(x, y) for x, y in simplify(r, tol)]
        parts.append("M" + " L".join(f"{a},{b}" for a, b in pts) + " Z")
    return " ".join(parts)


def classify(values: dict, n: int = 5) -> tuple[dict, list]:
    """Quantile classes 0..n-1 for positive values; returns (class by key, upper bounds)."""
    vals = sorted(v for v in values.values() if v > 0)
    if not vals:
        return {}, []
    bounds = [vals[min(len(vals) - 1, math.ceil(len(vals) * (i + 1) / n) - 1)] for i in range(n)]
    out = {}
    for k, v in values.items():
        if v > 0:
            out[k] = next(i for i, b in enumerate(bounds) if v <= b)
    return out, bounds


def marker(shape: str, x: float, y: float, r: float = 7) -> str:
    st = 'fill="#ffffff" stroke="#000000" stroke-width="2"'
    if shape == "circle":
        return f'<circle cx="{x}" cy="{y}" r="{r}" {st}/>'
    if shape == "triangle":
        return (f'<polygon points="{x},{y - r * 1.2} {x + r * 1.1},{y + r * 0.8} '
                f'{x - r * 1.1},{y + r * 0.8}" {st}/>')
    if shape == "diamond":
        return f'<polygon points="{x},{y - r * 1.2} {x + r * 1.2},{y} {x},{y + r * 1.2} {x - r * 1.2},{y}" {st}/>'
    return (f'<rect x="{x - r}" y="{y - r}" width="{2 * r}" height="{2 * r}" {st}/>'
            f'<path d="M{x - r},{y - r} L{x + r},{y + r} M{x + r},{y - r} L{x - r},{y + r}" '
            f'stroke="#000000" stroke-width="1.5"/>')


def render(tracts: list, values: dict, at_risk: set, sites: list, title: str,
           width: int = 720, height: int = 520, tol: float = 0.0008,
           labels: dict | None = None) -> str:
    """tracts: features with properties.tract_fips; values: fips -> AFN need;
    sites: [{"n": label number, "lon", "lat", "status"}];
    labels: fips -> readable tract label, shown as a hover tooltip."""
    proj = Projection(extent(tracts), width, height)
    cls, bounds = classify({k: v for k, v in values.items() if k in at_risk})
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
           f'width="100%" role="img" aria-labelledby="maptitle">',
           f'<title id="maptitle">{escape(title)}</title>',
           f'<rect width="{width}" height="{height}" fill="#ffffff"/>']
    for f in tracts:
        fips = f["properties"]["tract_fips"]
        d = path_d(f["geometry"], proj, tol)
        if not d:
            continue
        risk = fips in at_risk
        fill = RAMP[cls[fips]] if fips in cls else NOT_AT_RISK
        stroke = ('stroke="#000000" stroke-width="1.4"' if risk
                  else 'stroke="#9a9a9a" stroke-width="0.5" stroke-dasharray="2,2"')
        tip = (labels or {}).get(fips)
        out.append(f'<path d="{d}" fill="{fill}" {stroke}><title>{escape(tip)}</title></path>'
                   if tip else f'<path d="{d}" fill="{fill}" {stroke}/>')
    for s in sites:
        x, y = proj(s["lon"], s["lat"])
        shape = MARKERS.get(s["status"], ("circle", ""))[0]
        out.append(marker(shape, x, y))
        out.append(f'<text x="{x + 10}" y="{y + 4}" font-family="Arial, Helvetica, sans-serif" '
                   f'font-size="13" font-weight="bold" stroke="#ffffff" stroke-width="3" '
                   f'paint-order="stroke">{s["n"]}</text>')
    out.append("</svg>")
    return "\n".join(out), bounds


def legend(bounds: list) -> str:
    """HTML legend: color swatches with numeric labels, marker shapes with text labels."""
    items, lo = [], 0
    for i, (b, name) in enumerate(zip(bounds, need_names(len(bounds)))):
        items.append(f'<li><svg width="28" height="16" aria-hidden="true"><rect width="28" '
                     f'height="16" fill="{RAMP[i]}" stroke="#000"/></svg> {name} '
                     f'<span class="range">({lo:,.0f}–{b:,.0f} people)</span></li>')
        lo = b
    items.append('<li><svg width="28" height="16" aria-hidden="true"><rect width="28" height="16" '
                 'fill="#fff" stroke="#000" stroke-width="2"/></svg> Solid outline: Census area '
                 'in the risk area</li>')
    items.append('<li><svg width="28" height="16" aria-hidden="true"><rect width="28" height="16" '
                 'fill="#fff" stroke="#9a9a9a" stroke-dasharray="2,2"/></svg> Dashed outline: '
                 'outside the risk area</li>')
    seen = set()
    for status, (shape, label) in MARKERS.items():
        if label in seen:
            continue
        seen.add(label)
        items.append(f'<li><svg width="28" height="22" aria-hidden="true">'
                     f'{marker(shape, 14, 11, 6)}</svg> {escape(label)}</li>')
    return '<ul class="legend">' + "".join(items) + "</ul>"
