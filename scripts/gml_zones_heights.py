"""
scripts/gml_zones_heights.py

Produces a clean zone_id -> polygon -> max_height lookup
by spatially joining Maatvoering label points to Bouwvlak polygons.

Output: data/outputs/draka_zones_heights.json

Usage:
    .venv/bin/python scripts/gml_zones_heights.py
"""

from __future__ import annotations
import json
from pathlib import Path
from lxml import etree
from shapely.geometry import Point, Polygon

GML_CACHE = Path("data/cache/NL.IMRO.0363.N2102BPGST-VG01.gml")
OUTPUT    = Path("data/outputs/draka_zones_heights.json")

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def get_ns(root) -> str:
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if el.nsmap:
            return el.nsmap.get(None) or next(iter(el.nsmap.values()))
    raise ValueError("No namespace found")

def parse_poslist(text: str) -> list[tuple[float, float]]:
    nums = [float(x) for x in text.strip().split()]
    return [(nums[i], nums[i+1]) for i in range(0, len(nums), 2)]

# ---------------------------------------------------------------------
# Extract bouwvlakken (polygon geometry)
# ---------------------------------------------------------------------

def extract_bouwvlakken(root, IMRO: str, GML: str) -> list[dict]:
    bouwvlakken = []
    for el in root.iter(f"{IMRO}Bouwvlak"):
        gml_id = el.get(f"{GML}id", "")

        # Extract bestemmingsvlak reference (useful for linking to bestemming)
        bv_ref_el = el.find(f"{IMRO}bestemmingsvlak")
        bv_ref = ""
        if bv_ref_el is not None:
            href = bv_ref_el.get("{http://www.w3.org/1999/xlink}href", "")
            bv_ref = href.lstrip("#")

        # Extract polygon from posList
        pos_el = el.find(f".//{GML}posList")
        if pos_el is None or not pos_el.text:
            continue
        coords = parse_poslist(pos_el.text)
        if len(coords) < 3:
            continue

        bouwvlakken.append({
            "id":               gml_id,
            "bestemmingsvlak":  bv_ref,
            "polygon_rd":       coords,
            "shapely":          Polygon(coords),
        })

    return bouwvlakken

# ---------------------------------------------------------------------
# Extract maatvoeringen (height label + position)
# ---------------------------------------------------------------------

def extract_maatvoeringen(root, IMRO: str, GML: str) -> list[dict]:
    maatvoeringen = []
    for el in root.iter(f"{IMRO}Maatvoering"):
        gml_id = el.get(f"{GML}id", "")

        # Label position point
        pos_el = el.find(f".//{GML}pos")
        if pos_el is None or not pos_el.text:
            continue
        xy = [float(v) for v in pos_el.text.strip().split()]
        if len(xy) != 2:
            continue
        point = Point(xy[0], xy[1])

        # Height value
        waarde_el = el.find(f".//{IMRO}waarde")
        type_el   = el.find(f".//{IMRO}waardeType")
        if waarde_el is None:
            continue

        raw = waarde_el.text.strip().replace(",", ".")
        try:
            height = float(raw)
        except ValueError:
            continue

        waarde_type = type_el.text.strip() if type_el is not None else ""
        if "bouwhoogte" not in waarde_type.lower():
            continue  # skip non-height maatvoeringen

        maatvoeringen.append({
            "id":          gml_id,
            "height_m":    height,
            "waarde_type": waarde_type,
            "point":       point,
            "coords_rd":   xy,
        })

    return maatvoeringen

# ---------------------------------------------------------------------
# Spatial join: assign each maatvoering to its bouwvlak
# ---------------------------------------------------------------------

def spatial_join(bouwvlakken: list[dict], maatvoeringen: list[dict]) -> list[dict]:
    results = []

    for bv in bouwvlakken:
        poly    = bv["shapely"]
        matched = []

        for m in maatvoeringen:
            if poly.contains(m["point"]):
                matched.append(m)

        # Take the max height if multiple labels fall in one zone
        max_height = max((m["height_m"] for m in matched), default=None)

        results.append({
            "zone_id":          bv["id"],
            "bestemmingsvlak":  bv["bestemmingsvlak"],
            "max_height_m":     max_height,
            "matched_labels":   [
                {"id": m["id"], "height_m": m["height_m"], "coords_rd": m["coords_rd"]}
                for m in matched
            ],
            "polygon_rd":       bv["polygon_rd"],
        })

    # Flag any maatvoeringen that didn't land inside any bouwvlak
    assigned_ids = {
        m["id"]
        for bv_result in results
        for m in bv_result["matched_labels"]
    }
    unmatched = [m for m in maatvoeringen if m["id"] not in assigned_ids]
    if unmatched:
        print(f"\nWARNING: {len(unmatched)} maatvoering(en) not inside any bouwvlak:")
        for m in unmatched:
            print(f"  {m['id']}  height={m['height_m']}m  coords={m['coords_rd']}")

    return results

# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():
    raw  = GML_CACHE.read_bytes()
    root = etree.fromstring(raw)

    ns_uri = get_ns(root)
    IMRO   = f"{{{ns_uri}}}"
    GML    = "{http://www.opengis.net/gml/3.2}"

    print("Extracting bouwvlakken...")
    bouwvlakken   = extract_bouwvlakken(root, IMRO, GML)
    print(f"  Found {len(bouwvlakken)}")

    print("Extracting maatvoeringen...")
    maatvoeringen = extract_maatvoeringen(root, IMRO, GML)
    print(f"  Found {len(maatvoeringen)}")

    print("Joining spatially...")
    results = spatial_join(bouwvlakken, maatvoeringen)

    # Strip shapely objects before serialising
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, indent=2))

    print(f"\n=== RESULT ===")
    print(f"{'Zone ID':<45s}  {'Max height':>10}  Labels")
    print("-" * 70)
    for r in results:
        h  = f"{r['max_height_m']}m" if r["max_height_m"] else "NO MATCH"
        n  = len(r["matched_labels"])
        print(f"  {r['zone_id'][-36:]:<36s}  {h:>10s}  ({n} label(s))")

    print(f"\nWritten to {OUTPUT}")

if __name__ == "__main__":
    main()