"""Small pure-Python geometry helpers (GeoJSON, WGS84). No dependencies."""
from __future__ import annotations


def point_in_ring(x: float, y: float, ring: list) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def point_in_polygon(x: float, y: float, rings: list) -> bool:
    """rings[0] = outer boundary, rings[1:] = holes."""
    if not rings or not point_in_ring(x, y, rings[0]):
        return False
    return not any(point_in_ring(x, y, h) for h in rings[1:])


def point_in_geometry(x: float, y: float, geom: dict | None) -> bool:
    if not geom:
        return False
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Polygon":
        return point_in_polygon(x, y, c)
    if t == "MultiPolygon":
        return any(point_in_polygon(x, y, p) for p in c)
    return False


def _coords(geom: dict):
    def walk(c):
        if isinstance(c[0], (int, float)):
            yield c
        else:
            for s in c:
                yield from walk(s)
    yield from walk(geom["coordinates"])


def bbox_of(geom: dict) -> tuple:
    xs, ys = zip(*((c[0], c[1]) for c in _coords(geom)))
    return min(xs), min(ys), max(xs), max(ys)


def sample_points(geom: dict, n: int = 100) -> list:
    """Regular grid of points inside a polygon (about n points)."""
    x0, y0, x1, y1 = bbox_of(geom)
    side = max(int(n ** 0.5), 1)
    pts = []
    for i in range(side):
        for j in range(side):
            x = x0 + (i + 0.5) * (x1 - x0) / side
            y = y0 + (j + 0.5) * (y1 - y0) / side
            if point_in_geometry(x, y, geom):
                pts.append((x, y))
    if not pts:  # very thin polygon: fall back to a vertex
        c = next(_coords(geom))
        pts.append((c[0], c[1]))
    return pts


def representative_point(geom: dict) -> tuple:
    pts = sample_points(geom, 64)
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    if point_in_geometry(cx, cy, geom):
        return cx, cy
    return min(pts, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)


class ZoneIndex:
    """Polygon layer with bbox prefilter. Enough for a few thousand queries."""

    def __init__(self, fc: dict | None, key: str | None = None):
        self.items = []
        for f in (fc or {}).get("features", []):
            g = f.get("geometry")
            if g and g.get("type") in ("Polygon", "MultiPolygon"):
                k = (f.get("properties") or {}).get(key) if key else None
                self.items.append((bbox_of(g), g, k, f))

    def __bool__(self):
        return bool(self.items)

    def find(self, x: float, y: float):
        for (x0, y0, x1, y1), g, k, f in self.items:
            if x0 <= x <= x1 and y0 <= y <= y1 and point_in_geometry(x, y, g):
                return f
        return None

    def contains(self, x: float, y: float) -> bool:
        return self.find(x, y) is not None

    def share_inside(self, geom: dict, n: int = 100) -> float:
        """Approximate share of a polygon's area that falls in this layer."""
        if not self.items:
            return 0.0
        tb = bbox_of(geom)
        near = [it for it in self.items
                if not (it[0][2] < tb[0] or it[0][0] > tb[2]
                        or it[0][3] < tb[1] or it[0][1] > tb[3])]
        if not near:
            return 0.0
        pts = sample_points(geom, n)
        hit = sum(1 for x, y in pts
                  if any(b[0] <= x <= b[2] and b[1] <= y <= b[3]
                         and point_in_geometry(x, y, g) for b, g, _, _ in near))
        return hit / len(pts)
