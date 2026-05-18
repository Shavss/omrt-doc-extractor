"""
scripts/gml_zone_framework.py

Builds the authoritative zone framework for the Draka Terrein bestemmingsplan
from the cached GML file. One entry per bouwvlak, enriched with:
  - linked enkelbestemming (bestemmingsvlak href)
  - sgd functieaanduiding (programme zone code)
  - max bouwhoogte from spatial join on Maatvoering label points
  - sba bouwaanduidingen (split into building modifiers vs acoustic 'dove gevel')
  - overlap flags for Waarde - Archeologie and geluidzone - industrie
  - polygon in both RD New (EPSG:28992) and WGS84

Also emits the site boundary (plangebied) and no-build zones
(Groen, Verkeer, vrijwaringszone-vaarweg).

Output: data/outputs/approach_gml/zone_framework.json

Usage:
    .venv/bin/python scripts/gml_zone_framework.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lxml import etree
from pyproj import Transformer
from shapely.geometry import Point, Polygon

GML_CACHE = Path("data/cache/NL.IMRO.0363.N2102BPGST-VG01.gml")
OUTPUT_DIR = Path("data/outputs/draka/approach_gml")
OUTPUT = OUTPUT_DIR / "zone_framework_gml.json"

IMRO_NS = "http://www.geonovum.nl/imro/2012/1.1"
GML_NS = "http://www.opengis.net/gml/3.2"
XLINK_NS = "http://www.w3.org/1999/xlink"

IMRO = f"{{{IMRO_NS}}}"
GML = f"{{{GML_NS}}}"
XLINK = f"{{{XLINK_NS}}}"

_transformer = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)


def parse_poslist(text: str) -> list[tuple[float, float]]:
    nums = [float(x) for x in text.strip().split()]
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums), 2)]


def first_polygon_rd(el) -> list[tuple[float, float]] | None:
    pos_el = el.find(f".//{GML}posList")
    if pos_el is None or not pos_el.text:
        return None
    coords = parse_poslist(pos_el.text)
    return coords if len(coords) >= 3 else None


def all_polygons_rd(el) -> list[list[tuple[float, float]]]:
    """All exterior rings found under `el`. Handles MultiSurface / multi-part."""
    out: list[list[tuple[float, float]]] = []
    for pos_el in el.iter(f"{GML}posList"):
        if not pos_el.text:
            continue
        coords = parse_poslist(pos_el.text)
        if len(coords) >= 3:
            out.append(coords)
    return out


def union_polygon_rd(el) -> list[tuple[float, float]] | None:
    """Union all rings under `el` into a single outer boundary (RD).

    Falls back to the first ring if shapely fails or there's only one.
    """
    rings = all_polygons_rd(el)
    if not rings:
        return None
    if len(rings) == 1:
        return rings[0]
    try:
        from shapely.geometry import Polygon
        from shapely.ops import unary_union

        polys = [Polygon(r) for r in rings if len(r) >= 3]
        # Self-intersecting rings are common in IMRO/GML exports; buffer(0)
        # repairs them before union.
        polys = [p if p.is_valid else p.buffer(0) for p in polys]
        merged = unary_union(polys)
        if merged.geom_type == "Polygon":
            return [(x, y) for x, y in merged.exterior.coords]
        # MultiPolygon: take the convex hull so we still get a single closed ring
        hull = merged.convex_hull
        if hull.geom_type == "Polygon":
            return [(x, y) for x, y in hull.exterior.coords]
    except Exception:  # noqa: BLE001
        pass
    return rings[0]


def to_wgs84(coords_rd: list[tuple[float, float]]) -> list[list[float]]:
    return [list(_transformer.transform(x, y)) for x, y in coords_rd]


def get_text(el, local_name: str) -> str:
    child = el.find(f"{IMRO}{local_name}")
    return child.text.strip() if child is not None and child.text else ""


def get_href(el, local_name: str) -> str:
    child = el.find(f"{IMRO}{local_name}")
    if child is None:
        return ""
    return child.get(f"{XLINK}href", "").lstrip("#")


def short_id(gml_id: str) -> str:
    # strip the "NL.IMRO." prefix for readability
    return gml_id.replace("NL.IMRO.", "")


def normalise_sba(naam: str) -> str:
    """Map 'specifieke bouwaanduiding - dove gevel N' -> 'sba-dvgN',
    'specifieke bouwaanduiding - N' -> 'sba-N'."""
    m = re.match(r"specifieke bouwaanduiding\s*-\s*dove gevel\s*(\d+)", naam, re.I)
    if m:
        return f"sba-dvg{m.group(1)}"
    m = re.match(r"specifieke bouwaanduiding\s*-\s*(\S+)", naam, re.I)
    if m:
        return f"sba-{m.group(1)}"
    return naam


def sgd_code_from_naam(naam: str) -> str:
    m = re.search(r"(\d+)\s*$", naam)
    return f"sgd-{m.group(1)}" if m else ""


def extract_bouwvlakken(root) -> list[dict]:
    out = []
    for el in root.iter(f"{IMRO}Bouwvlak"):
        coords = first_polygon_rd(el)
        if coords is None:
            continue
        poly = Polygon(coords)
        out.append({
            "gml_id": el.get(f"{GML}id", ""),
            "bestemmingsvlak_href": get_href(el, "bestemmingsvlak"),
            "polygon_rd": coords,
            "shapely": _clean(poly),
        })
    return out


def extract_maatvoeringen(root) -> list[dict]:
    out = []
    for el in root.iter(f"{IMRO}Maatvoering"):
        pos_el = el.find(f".//{GML}pos")
        if pos_el is None or not pos_el.text:
            continue
        xy = [float(v) for v in pos_el.text.strip().split()]
        if len(xy) != 2:
            continue

        waarde_el = el.find(f".//{IMRO}waarde")
        type_el = el.find(f".//{IMRO}waardeType")
        if waarde_el is None or waarde_el.text is None:
            continue
        try:
            height = float(waarde_el.text.strip().replace(",", "."))
        except ValueError:
            continue
        waarde_type = type_el.text.strip() if type_el is not None and type_el.text else ""
        if "bouwhoogte" not in waarde_type.lower():
            continue

        out.append({
            "height_m": height,
            "point": Point(xy[0], xy[1]),
        })
    return out


def extract_functieaanduidingen(root) -> list[dict]:
    out = []
    for el in root.iter(f"{IMRO}Functieaanduiding"):
        naam = get_text(el, "naam")
        out.append({
            "gml_id": el.get(f"{GML}id", ""),
            "bestemmingsvlak_href": get_href(el, "bestemmingsvlak"),
            "naam": naam,
            "sgd_code": sgd_code_from_naam(naam),
        })
    return out


def extract_bouwaanduidingen(root) -> list[dict]:
    out = []
    for el in root.iter(f"{IMRO}Bouwaanduiding"):
        naam = get_text(el, "naam")
        coords = first_polygon_rd(el)
        poly = Polygon(coords) if coords else None
        out.append({
            "gml_id": el.get(f"{GML}id", ""),
            "naam": naam,
            "code": normalise_sba(naam),
            "is_acoustic": "dove gevel" in naam.lower(),
            "shapely": _clean(poly) if poly is not None else None,
        })
    return out


def extract_enkelbestemmingen(root) -> list[dict]:
    out = []
    for el in root.iter(f"{IMRO}Enkelbestemming"):
        coords = first_polygon_rd(el)
        out.append({
            "gml_id": el.get(f"{GML}id", ""),
            "naam": get_text(el, "naam"),
            "polygon_rd": coords,
        })
    return out


def _clean(poly: Polygon) -> Polygon:
    if poly.is_valid:
        return poly
    return poly.buffer(0)


def extract_overlay_polygons(root, tag: str, name_match: str) -> list[Polygon]:
    polys = []
    for el in root.iter(f"{IMRO}{tag}"):
        naam = get_text(el, "naam")
        if name_match.lower() not in naam.lower():
            continue
        coords = first_polygon_rd(el)
        if coords:
            polys.append(_clean(Polygon(coords)))
    return polys


def assemble_framework(root) -> dict:
    bouwvlakken = extract_bouwvlakken(root)
    maatvoeringen = extract_maatvoeringen(root)
    functies = extract_functieaanduidingen(root)
    bouwaand = extract_bouwaanduidingen(root)

    wra_polys = extract_overlay_polygons(root, "Dubbelbestemming", "Waarde - Archeologie")
    geluid_polys = extract_overlay_polygons(root, "Gebiedsaanduiding", "geluidzone")

    # site boundary
    plangebied_el = next(root.iter(f"{IMRO}Bestemmingsplangebied"), None)
    site_rd = union_polygon_rd(plangebied_el) if plangebied_el is not None else None

    # no-build zones from enkelbestemming + vrijwaringszone gebiedsaanduiding
    no_build = []
    for eb in extract_enkelbestemmingen(root):
        if eb["naam"] in ("Groen", "Verkeer") and eb["polygon_rd"]:
            no_build.append({
                "type": "enkelbestemming",
                "naam": eb["naam"],
                "polygon_rd": [[round(x, 3), round(y, 3)] for x, y in eb["polygon_rd"]],
                "polygon_wgs84": to_wgs84(eb["polygon_rd"]),
            })
    for el in root.iter(f"{IMRO}Gebiedsaanduiding"):
        naam = get_text(el, "naam")
        if "vrijwaringszone" in naam.lower() and "vaarweg" in naam.lower():
            coords = first_polygon_rd(el)
            if coords:
                no_build.append({
                    "type": "gebiedsaanduiding",
                    "naam": naam,
                    "polygon_rd": [[round(x, 3), round(y, 3)] for x, y in coords],
                    "polygon_wgs84": to_wgs84(coords),
                })

    # zone framework
    zones = []
    # stable order: by RD centroid (north-to-south, west-to-east) for deterministic indexing
    bouwvlakken_sorted = sorted(
        bouwvlakken,
        key=lambda b: (-b["shapely"].centroid.y, b["shapely"].centroid.x),
    )
    for idx, bv in enumerate(bouwvlakken_sorted, start=1):
        poly = bv["shapely"]

        # heights via spatial join
        heights = [m["height_m"] for m in maatvoeringen if poly.contains(m["point"])]
        max_h = max(heights) if heights else None

        # functieaanduidingen linked by shared bestemmingsvlak href
        linked_fa = [
            f for f in functies
            if f["bestemmingsvlak_href"] == bv["bestemmingsvlak_href"] and f["sgd_code"]
        ]
        sgd_code = linked_fa[0]["sgd_code"] if linked_fa else ""
        sgd_full = linked_fa[0]["naam"] if linked_fa else ""

        # bouwaanduidingen by polygon intersection
        sba_codes: list[str] = []
        acoustic: list[str] = []
        for ba in bouwaand:
            if ba["shapely"] is None or not poly.intersects(ba["shapely"]):
                continue
            # avoid touching-only matches
            if poly.intersection(ba["shapely"]).area <= 0:
                continue
            if ba["is_acoustic"]:
                if ba["code"] not in acoustic:
                    acoustic.append(ba["code"])
            else:
                if ba["code"] not in sba_codes:
                    sba_codes.append(ba["code"])

        overlaps_wra = any(poly.intersects(p) and poly.intersection(p).area > 0 for p in wra_polys)
        overlaps_geluid = any(poly.intersects(p) and poly.intersection(p).area > 0 for p in geluid_polys)

        zones.append({
            "zone_index": idx,
            "bouwvlak_id": short_id(bv["gml_id"]),
            "bestemmingsvlak_id": short_id(bv["bestemmingsvlak_href"]),
            "sgd_code": sgd_code,
            "sgd_full_name": sgd_full,
            "max_height_m": max_h,
            "all_heights_m": sorted(heights),
            "footprint_area_m2": round(poly.area, 2),
            "sba_codes": sorted(sba_codes),
            "acoustic_overlays": sorted(acoustic),
            "overlaps_wra": overlaps_wra,
            "overlaps_geluidzone": overlaps_geluid,
            "polygon_rd": [[round(x, 3), round(y, 3)] for x, y in bv["polygon_rd"]],
            "polygon_wgs84": [[round(lon, 8), round(lat, 8)] for lon, lat in to_wgs84(bv["polygon_rd"])],
        })

    return {
        "plan_id": "NL.IMRO.0363.N2102BPGST-VG01",
        "crs_rd": "EPSG:28992",
        "crs_wgs84": "EPSG:4326",
        "site_boundary_rd": [[round(x, 3), round(y, 3)] for x, y in site_rd] if site_rd else None,
        "site_boundary_wgs84": to_wgs84(site_rd) if site_rd else None,
        "zones": zones,
        "no_build_zones": no_build,
    }


def print_summary(framework: dict) -> None:
    print()
    print(f"{'zone':>4} | {'sgd':>6} | {'h_max':>6} | {'area_m2':>9} | sba_codes              | acoustic_overlays")
    print("-" * 100)
    for z in framework["zones"]:
        h = f"{z['max_height_m']:.1f}" if z["max_height_m"] is not None else "  -  "
        print(
            f"{z['zone_index']:>4} | "
            f"{z['sgd_code'] or '-':>6} | "
            f"{h:>6} | "
            f"{z['footprint_area_m2']:>9.1f} | "
            f"{','.join(z['sba_codes']) or '-':<22} | "
            f"{','.join(z['acoustic_overlays']) or '-'}"
        )
    print()
    print(f"site boundary: {'yes' if framework['site_boundary_rd'] else 'no'}")
    print(f"no-build zones: {len(framework['no_build_zones'])}")


def main() -> None:
    root = etree.fromstring(GML_CACHE.read_bytes())
    framework = assemble_framework(root)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(framework, indent=2))
    print(f"Wrote {OUTPUT}")
    print_summary(framework)


if __name__ == "__main__":
    main()
