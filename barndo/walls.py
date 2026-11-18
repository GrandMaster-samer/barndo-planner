"""Derive wall segments from the space layout."""
from __future__ import annotations

from .layout import Layout, OPEN_TO_EACH_OTHER, shared_edge


def interior_walls(layout: Layout) -> list[tuple[str, float, float, float, str]]:
    """List of (axis, fixed, lo, hi, kind) for every interior wall.

    kind: 'int' for ordinary partitions, 'shop' for the shop/living separation.
    Boundaries between open spaces (great room, hallway, links) get no wall.
    """
    walls = []
    sp = layout.spaces
    for i in range(len(sp)):
        for j in range(i + 1, len(sp)):
            a, b = sp[i], sp[j]
            e = shared_edge(a, b)
            if not e:
                continue
            if a.kind in OPEN_TO_EACH_OTHER and b.kind in OPEN_TO_EACH_OTHER:
                continue
            kind = "shop" if "shop" in (a.kind, b.kind) else "int"
            walls.append((e[0], e[1], e[2], e[3], kind))
    return _merge(walls)


def _merge(walls):
    """Merge collinear, touching segments of the same kind."""
    walls = sorted(walls, key=lambda w: (w[0], w[4], round(w[1], 4), w[2]))
    out = []
    for w in walls:
        if out:
            p = out[-1]
            if p[0] == w[0] and p[4] == w[4] and abs(p[1] - w[1]) < 1e-6 and w[2] <= p[3] + 1e-6:
                out[-1] = (p[0], p[1], p[2], max(p[3], w[3]), p[4])
                continue
        out.append(w)
    return out


def interior_wall_length(layout: Layout) -> float:
    return sum(w[3] - w[2] for w in interior_walls(layout))
