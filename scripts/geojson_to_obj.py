"""
scripts/geojson_to_obj.py

Converts draka_grasshopper.geojson bouwvlakken to an extruded OBJ.
Each bouwvlak is extruded to its max_height_m.
Non-bouwvlak features are written as flat polygons at z=0.

Usage:
    .venv/bin/python scripts/geojson_to_obj.py
"""

from __future__ import annotations

import json
from pathlib import Path

from pyproj import Transformer

INPUT = Path("data/outputs/draka_grasshopper.geojson")
OUTPUT = Path("data/outputs/draka_zones.obj")

# WGS84 -> RD New (metric, so OBJ is in metres)
WGS84_TO_RD = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)


def wgs84_ring_to_rd(ring: list) -> list[tuple[float, float]]:
    return [WGS84_TO_RD.transform(lon, lat) for lon, lat in ring]


def localise(coords: list[tuple], origin: tuple) -> list[tuple]:
    ox, oy = origin
    return [(x - ox, y - oy) for x, y in coords]


def write_obj(features: list[dict], origin: tuple, f_out):
    vertex_index = 1  # OBJ is 1-indexed

    for feat in features:
        props = feat["properties"]
        obj_type = props.get("object_type", "unknown")
        height = props.get("max_height_m") or 0.0
        naam = props.get("naam", "")
        feat_id = props.get("id", "")[:16]

        ring_wgs84 = feat["geometry"]["coordinates"][0]
        ring_rd = wgs84_ring_to_rd(ring_wgs84)
        ring_local = localise(ring_rd, origin)

        # Drop closing vertex if it duplicates first
        if ring_local[0] == ring_local[-1]:
            ring_local = ring_local[:-1]

        n = len(ring_local)
        if n < 3:
            continue

        f_out.write(f"# {obj_type} | {naam} | h={height}m | {feat_id}\n")
        f_out.write(f"o {obj_type}_{feat_id}\n")

        if obj_type == "bouwvlak" and height > 0:
            # Bottom ring
            bottom_start = vertex_index
            for x, y in ring_local:
                f_out.write(f"v {x:.3f} {y:.3f} 0.000\n")
            vertex_index += n

            # Top ring
            top_start = vertex_index
            for x, y in ring_local:
                f_out.write(f"v {x:.3f} {y:.3f} {height:.3f}\n")
            vertex_index += n

            # Bottom face
            bottom_verts = " ".join(str(i) for i in range(bottom_start, bottom_start + n))
            f_out.write(f"f {bottom_verts}\n")

            # Top face
            top_verts = " ".join(str(i) for i in range(top_start, top_start + n))
            f_out.write(f"f {top_verts}\n")

            # Side faces
            for i in range(n):
                j = (i + 1) % n
                b0 = bottom_start + i
                b1 = bottom_start + j
                t0 = top_start + i
                t1 = top_start + j
                f_out.write(f"f {b0} {b1} {t1} {t0}\n")

        else:
            # Flat polygon at z=0
            for x, y in ring_local:
                f_out.write(f"v {x:.3f} {y:.3f} 0.000\n")
            verts = " ".join(str(i) for i in range(vertex_index, vertex_index + n))
            f_out.write(f"f {verts}\n")
            vertex_index += n

        f_out.write("\n")


def main():
    data = json.loads(INPUT.read_text())
    features = data["features"]

    # Compute origin from first bouwvlak centroid for local coordinates
    bouwvlakken = [f for f in features if f["properties"]["object_type"] == "bouwvlak"]
    first_ring = bouwvlakken[0]["geometry"]["coordinates"][0]
    first_rd = wgs84_ring_to_rd(first_ring)
    origin = (
        sum(x for x, y in first_rd) / len(first_rd),
        sum(y for x, y in first_rd) / len(first_rd),
    )
    print(f"Origin (RD New): {origin[0]:.1f}, {origin[1]:.1f}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        f.write("# Draka Terrein Hamerkwartier\n")
        f.write("# Generated from NL.IMRO.0363.N2102BPGST-VG01 GML\n")
        f.write(f"# Origin RD New: {origin[0]:.3f} {origin[1]:.3f}\n\n")
        write_obj(features, origin, f)

    print(f"Written to {OUTPUT}")

    # Quick summary
    by_type: dict[str, int] = {}
    for f in features:
        t = f["properties"]["object_type"]
        by_type[t] = by_type.get(t, 0) + 1
    for t, c in sorted(by_type.items()):
        print(f"  {t:<25s} {c} objects")


if __name__ == "__main__":
    main()
