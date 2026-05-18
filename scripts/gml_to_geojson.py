"""
scripts/gml_to_geojson.py

Extracts all spatial objects from the Draka GML and writes a
Grasshopper-ready GeoJSON file with all properties attached.

Coordinate system: RD New (EPSG:28992) -> WGS84 (EPSG:4326)

Output: data/outputs/draka_grasshopper.geojson

Usage:
    .venv/bin/python scripts/gml_to_geojson.py
"""

from __future__ import annotations
import json
from pathlib import Path
from lxml import etree
from shapely.geometry import Point, Polygon, mapping
from shapely.ops import transform
from pyproj import Transformer

GML_CACHE = Path("data/cache/NL.IMRO.0363.N2102BPGST-VG01.gml")
OUTPUT    = Path("data/outputs/draka_grasshopper.geojson")

# RD New -> WGS84
RD_TO_WGS84 = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)

def rd_to_wgs84(coords: list[tuple]) -> list[tuple]:
    return [RD_TO_WGS84.transform(x, y) for x, y in coords]

def get_ns(root) -> tuple[str, str]:
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if el.nsmap:
            ns_uri = el.nsmap.get(None) or next(iter(el.nsmap.values()))
            return f"{{{ns_uri}}}", "{http://www.opengis.net/gml/3.2}"
    raise ValueError("No namespace found")

def parse_poslist(text: str) -> list[tuple[float, float]]:
    nums = [float(x) for x in text.strip().split()]
    return [(nums[i], nums[i+1]) for i in range(0, len(nums), 2)]

def get_polygon(el, IMRO: str, GML: str) -> Polygon | None:
    pos_el = el.find(f".//{GML}posList")
    if pos_el is None or not pos_el.text:
        return None
    coords = parse_poslist(pos_el.text)
    if len(coords) < 3:
        return None
    return Polygon(coords)

def get_xlink(el, tag: str, IMRO: str) -> str:
    ref = el.find(f"{IMRO}{tag}")
    if ref is None:
        return ""
    return ref.get("{http://www.w3.org/1999/xlink}href", "").lstrip("#")

# ------------------------------------------------------------------
# Extract each object type
# ------------------------------------------------------------------

def extract_bouwvlakken(root, IMRO, GML, height_lookup: dict) -> list[dict]:
    features = []
    for el in root.iter(f"{IMRO}Bouwvlak"):
        gml_id  = el.get(f"{GML}id", "")
        poly_rd = get_polygon(el, IMRO, GML)
        if poly_rd is None:
            continue

        bv_ref = get_xlink(el, "bestemmingsvlak", IMRO)
        height = height_lookup.get(gml_id)

        coords_wgs84 = rd_to_wgs84(list(poly_rd.exterior.coords))

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords_wgs84]
            },
            "properties": {
                "object_type":      "bouwvlak",
                "id":               gml_id,
                "bestemmingsvlak":  bv_ref,
                "max_height_m":     height,
                "area_m2":          round(poly_rd.area, 1),
            }
        })
    return features


def extract_enkelbestemmingen(root, IMRO, GML) -> list[dict]:
    features = []
    for el in root.iter(f"{IMRO}Enkelbestemming"):
        gml_id  = el.get(f"{GML}id", "")
        poly_rd = get_polygon(el, IMRO, GML)
        if poly_rd is None:
            continue

        naam_el    = el.find(f"{IMRO}naam")
        artikel_el = el.find(f"{IMRO}artikelnummer")
        groep_el   = el.find(f"{IMRO}bestemmingshoofdgroep")

        coords_wgs84 = rd_to_wgs84(list(poly_rd.exterior.coords))

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords_wgs84]
            },
            "properties": {
                "object_type":   "enkelbestemming",
                "id":            gml_id,
                "naam":          naam_el.text.strip() if naam_el is not None else "",
                "artikel":       artikel_el.text.strip() if artikel_el is not None else "",
                "hoofdgroep":    groep_el.text.strip() if groep_el is not None else "",
                "area_m2":       round(poly_rd.area, 1),
            }
        })
    return features


def extract_functieaanduidingen(root, IMRO, GML) -> list[dict]:
    features = []
    for el in root.iter(f"{IMRO}Functieaanduiding"):
        gml_id  = el.get(f"{GML}id", "")
        poly_rd = get_polygon(el, IMRO, GML)
        if poly_rd is None:
            continue

        naam_el     = el.find(f"{IMRO}naam")
        aanduiding_el = el.find(f"{IMRO}aanduiding")

        coords_wgs84 = rd_to_wgs84(list(poly_rd.exterior.coords))

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords_wgs84]
            },
            "properties": {
                "object_type": "functieaanduiding",
                "id":          gml_id,
                "naam":        naam_el.text.strip() if naam_el is not None else "",
                "aanduiding":  aanduiding_el.text.strip() if aanduiding_el is not None else "",
                "area_m2":     round(poly_rd.area, 1),
            }
        })
    return features


def extract_bouwaanduidingen(root, IMRO, GML) -> list[dict]:
    features = []
    for el in root.iter(f"{IMRO}Bouwaanduiding"):
        gml_id  = el.get(f"{GML}id", "")
        poly_rd = get_polygon(el, IMRO, GML)
        if poly_rd is None:
            continue

        naam_el     = el.find(f"{IMRO}naam")
        aanduiding_el = el.find(f"{IMRO}aanduiding")

        coords_wgs84 = rd_to_wgs84(list(poly_rd.exterior.coords))

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords_wgs84]
            },
            "properties": {
                "object_type": "bouwaanduiding",
                "id":          gml_id,
                "naam":        naam_el.text.strip() if naam_el is not None else "",
                "aanduiding":  aanduiding_el.text.strip() if aanduiding_el is not None else "",
                "area_m2":     round(poly_rd.area, 1),
            }
        })
    return features


def extract_dubbelbestemmingen(root, IMRO, GML) -> list[dict]:
    features = []
    for el in root.iter(f"{IMRO}Dubbelbestemming"):
        gml_id  = el.get(f"{GML}id", "")
        poly_rd = get_polygon(el, IMRO, GML)
        if poly_rd is None:
            continue

        naam_el  = el.find(f"{IMRO}naam")
        groep_el = el.find(f"{IMRO}bestemmingshoofdgroep")

        coords_wgs84 = rd_to_wgs84(list(poly_rd.exterior.coords))

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords_wgs84]
            },
            "properties": {
                "object_type": "dubbelbestemming",
                "id":          gml_id,
                "naam":        naam_el.text.strip() if naam_el is not None else "",
                "hoofdgroep":  groep_el.text.strip() if groep_el is not None else "",
                "area_m2":     round(poly_rd.area, 1),
            }
        })
    return features


def extract_gebiedsaanduidingen(root, IMRO, GML) -> list[dict]:
    features = []
    for el in root.iter(f"{IMRO}Gebiedsaanduiding"):
        gml_id  = el.get(f"{GML}id", "")
        poly_rd = get_polygon(el, IMRO, GML)
        if poly_rd is None:
            continue

        naam_el     = el.find(f"{IMRO}naam")
        aanduiding_el = el.find(f"{IMRO}aanduiding")
        groep_el    = el.find(f"{IMRO}gebiedsaanduidinggroep")

        coords_wgs84 = rd_to_wgs84(list(poly_rd.exterior.coords))

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords_wgs84]
            },
            "properties": {
                "object_type": "gebiedsaanduiding",
                "id":          gml_id,
                "naam":        naam_el.text.strip() if naam_el is not None else "",
                "aanduiding":  aanduiding_el.text.strip() if aanduiding_el is not None else "",
                "groep":       groep_el.text.strip() if groep_el is not None else "",
                "area_m2":     round(poly_rd.area, 1),
            }
        })
    return features

# ------------------------------------------------------------------
# Build height lookup from spatial join (reuse gml_zones_heights logic)
# ------------------------------------------------------------------

def build_height_lookup(root, IMRO, GML) -> dict[str, float]:
    maatvoeringen = []
    for el in root.iter(f"{IMRO}Maatvoering"):
        pos_el    = el.find(f".//{GML}pos")
        waarde_el = el.find(f".//{IMRO}waarde")
        type_el   = el.find(f".//{IMRO}waardeType")
        if pos_el is None or waarde_el is None:
            continue
        if type_el is not None and "bouwhoogte" not in type_el.text.lower():
            continue
        xy = [float(v) for v in pos_el.text.strip().split()]
        if len(xy) != 2:
            continue
        try:
            height = float(waarde_el.text.strip().replace(",", "."))
        except ValueError:
            continue
        maatvoeringen.append((Point(xy[0], xy[1]), height))

    lookup = {}
    for el in root.iter(f"{IMRO}Bouwvlak"):
        gml_id  = el.get(f"{GML}id", "")
        poly_rd = get_polygon(el, IMRO, GML)
        if poly_rd is None:
            continue
        matched = [h for pt, h in maatvoeringen if poly_rd.contains(pt)]
        if matched:
            lookup[gml_id] = max(matched)

    return lookup

# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    raw  = GML_CACHE.read_bytes()
    root = etree.fromstring(raw)
    IMRO, GML = get_ns(root)

    print("Building height lookup...")
    height_lookup = build_height_lookup(root, IMRO, GML)
    print(f"  {len(height_lookup)} bouwvlakken with height assigned")

    print("Extracting all spatial objects...")
    features = []
    features += extract_bouwvlakken(root, IMRO, GML, height_lookup)
    features += extract_enkelbestemmingen(root, IMRO, GML)
    features += extract_functieaanduidingen(root, IMRO, GML)
    features += extract_bouwaanduidingen(root, IMRO, GML)
    features += extract_dubbelbestemmingen(root, IMRO, GML)
    features += extract_gebiedsaanduidingen(root, IMRO, GML)

    geojson = {
        "type": "FeatureCollection",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}
        },
        "metadata": {
            "plan_id":   "NL.IMRO.0363.N2102BPGST-VG01",
            "plan_naam": "Draka Terrein Hamerkwartier",
            "source":    "GML via ruimtelijkeplannen.nl",
            "crs_input": "EPSG:28992 (RD New)",
            "crs_output":"EPSG:4326 (WGS84)",
        },
        "features": features
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(geojson, indent=2))

    # Summary
    by_type: dict[str, int] = {}
    for f in features:
        t = f["properties"]["object_type"]
        by_type[t] = by_type.get(t, 0) + 1

    print(f"\n=== GEOJSON SUMMARY ===")
    for obj_type, count in sorted(by_type.items()):
        print(f"  {obj_type:<25s} {count}")
    print(f"  {'TOTAL':<25s} {len(features)}")
    print(f"\nWritten to {OUTPUT}")
    print(f"\nGrasshopper usage:")
    print(f"  Heron plugin  -> GH_GeoJSON component -> filter by object_type")
    print(f"  GH Python     -> import json; data = json.loads(File.ReadAllText(path))")
    print(f"  Filter bouwvlakken: [f for f in data['features'] if f['properties']['object_type']=='bouwvlak']")

if __name__ == "__main__":
    main()