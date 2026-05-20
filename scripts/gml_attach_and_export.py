"""
scripts/gml_attach_and_export.py

Reads the GML-derived zone framework and:
  Part A — attaches hardcoded programme rules (SGD/SBA/DVG) and writes
           zone_framework_with_rules.json
  Part B — emits draka_gml_parameters.json (flat consumable JSON)
  Part C — emits draka_gml.geojson (one feature per bouwvlak + boundary +
           no-build zones)
  Part D — emits draka_gml.obj (bouwvlakken extruded to max_height_m,
           localised to site centroid; no-build zones as flat polygons)

Programme rules are HARDCODED from the Draka bestemmingsplan regels
(NL.IMRO.0363.N2102BPGST-VG01) — artikel 3.2.2 / 3.3 / 3.4. In production
these would be extracted automatically from the DSO teksten API.

Usage:
    .venv/bin/python scripts/gml_attach_and_export.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from lxml import etree
from pyproj import Transformer
from shapely.geometry import Polygon

OUT_DIR = Path("data/outputs/draka/approach_gml")
FRAMEWORK_IN = OUT_DIR / "zone_framework_gml.json"
FRAMEWORK_OUT = OUT_DIR / "zone_framework_with_rules.json"
PARAMS_OUT = OUT_DIR / "draka_gml_parameters.json"
GEOJSON_OUT = OUT_DIR / "draka_gml.geojson"
OBJ_OUT = OUT_DIR / "draka_gml.obj"

GML_CACHE = Path("data/cache/NL.IMRO.0363.N2102BPGST-VG01.gml")
IMRO_NS = "http://www.geonovum.nl/imro/2012/1.1"
GML_NS = "http://www.opengis.net/gml/3.2"
IMRO = f"{{{IMRO_NS}}}"
GML = f"{{{GML_NS}}}"

_to_wgs = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)

# ---------------------------------------------------------------------
# Hardcoded rules (Draka bestemmingsplan, artikel 3.2.2 / 3.3 / 3.4)
# In production these would come from the DSO teksten API via plan IMRO ID.
# ---------------------------------------------------------------------

SGD_RULES: dict[str, dict] = {
    "specifieke vorm van gemengd - 1": {
        "sgd_code": "sgd-1",
        "allows_wonen": True,
        "productive_required_first_m2": None,
        "horeca_dienstverlening_cultuur_max_m2": 4000,
        "floor_plate_cap_exempt": False,
        "setback_trigger_m": 21,
        "setback_depth_m": 2.5,
        "source": "artikel 3.3.1 + 3.4",
    },
    "specifieke vorm van gemengd - 2": {
        "sgd_code": "sgd-2",
        "allows_wonen": True,
        "productive_required_first_m2": 2000,
        "horeca_dienstverlening_cultuur_max_m2": 4000,
        "floor_plate_cap_exempt": False,
        "setback_trigger_m": 21,
        "setback_depth_m": 2.5,
        "source": "artikel 3.3.2 + 3.4.2",
    },
    "specifieke vorm van gemengd - 3": {
        "sgd_code": "sgd-3",
        "allows_wonen": True,
        "productive_required_first_m2": 2000,
        "horeca_dienstverlening_cultuur_max_m2": 4000,
        "floor_plate_cap_exempt": False,
        "setback_trigger_m": 21,
        "setback_depth_m": 2.5,
        "source": "artikel 3.3.3 + 3.4.3",
    },
    "specifieke vorm van gemengd - 4": {
        "sgd_code": "sgd-4",
        "allows_wonen": True,
        "productive_required_first_m2": 1000,
        "horeca_dienstverlening_cultuur_max_m2": 4000,
        "floor_plate_cap_exempt": True,
        "setback_trigger_m": 21,
        "setback_depth_m": 2.5,
        "source": "artikel 3.3.4 + 3.4.4 + 3.2.2",
    },
    "specifieke vorm van gemengd - 5": {
        "sgd_code": "sgd-5",
        "allows_wonen": False,
        "productive_required_first_m2": None,
        "horeca_dienstverlening_cultuur_max_m2": 1500,
        "floor_plate_cap_exempt": False,
        "setback_trigger_m": 21,
        "setback_depth_m": 2.5,
        "source": "artikel 3.3.5",
    },
    "specifieke vorm van gemengd - 6": {
        "sgd_code": "sgd-6",
        "allows_wonen": True,
        "productive_required_first_m2": 3000,
        "horeca_dienstverlening_cultuur_max_m2": 3000,
        "floor_plate_cap_exempt": False,
        "setback_trigger_m": 21,
        "setback_depth_m": 2.5,
        "source": "artikel 3.3.6 + 3.4.5",
    },
    "specifieke vorm van gemengd - 7": {
        "sgd_code": "sgd-7",
        "allows_wonen": False,
        "productive_required_first_m2": None,
        "horeca_dienstverlening_cultuur_max_m2": 4000,
        "floor_plate_cap_exempt": False,
        "setback_trigger_m": 21,
        "setback_depth_m": 2.5,
        "source": "artikel 3.3.7",
    },
    "specifieke vorm van gemengd - 8": {
        "sgd_code": "sgd-8",
        "allows_wonen": False,
        "productive_required_first_m2": None,
        "horeca_dienstverlening_cultuur_max_m2": 4000,
        "floor_plate_cap_exempt": False,
        "setback_trigger_m": 21,
        "setback_depth_m": 2.5,
        "source": "artikel 3.3.8",
    },
    "specifieke vorm van gemengd - 9": {
        "sgd_code": "sgd-9",
        "allows_wonen": False,
        "productive_required_first_m2": None,
        "horeca_dienstverlening_cultuur_max_m2": None,
        "floor_plate_cap_exempt": False,
        "setback_trigger_m": 21,
        "setback_depth_m": 2.5,
        "source": "artikel 3.3 + kaveltekening aanduiding sgd-9",
    },
    "maatschappelijk": {
        "sgd_code": "maatschappelijk",
        "allows_wonen": False,
        "productive_required_first_m2": None,
        "horeca_dienstverlening_cultuur_max_m2": None,
        "floor_plate_cap_exempt": False,
        "setback_trigger_m": 21,
        "setback_depth_m": 2.5,
        "source": "artikel 3.1 + 3.3.9",
    },
}

SBA_MODIFIERS: dict[str, dict] = {
    "specifieke bouwaanduiding - 1": {
        "sba_code": "sba-1",
        "setback_trigger_m": 30.5,
        "source": "artikel 3.2.2",
    },
    "specifieke bouwaanduiding - 2": {
        "sba_code": "sba-2",
        "setback_trigger_m": 21,
        "source": "artikel 3.2.2",
    },
    "specifieke bouwaanduiding - 3": {
        "sba_code": "sba-3",
        "setback_trigger_m": 30.5,
        "source": "artikel 3.2.2",
    },
    "specifieke bouwaanduiding - 4": {
        "sba_code": "sba-4",
        "floor_plate_cap_exempt": True,
        "source": "artikel 3.2.2",
    },
}

DVG_THRESHOLDS: dict[str, dict] = {
    "specifieke bouwaanduiding - dove gevel 1": {"threshold_m": 21.0, "source": "artikel 3.2.2"},
    "specifieke bouwaanduiding - dove gevel 2": {"threshold_m": 30.0, "source": "artikel 3.2.2"},
    "specifieke bouwaanduiding - dove gevel 3": {"threshold_m": 22.5, "source": "artikel 3.2.2"},
    "specifieke bouwaanduiding - dove gevel 4": {"threshold_m": 58.5, "source": "artikel 3.2.2"},
    "specifieke bouwaanduiding - dove gevel 5": {"threshold_m": 40.0, "source": "artikel 3.2.2"},
}

SITE_CONSTRAINTS: dict = {
    "max_bvo_total_m2": 151400,
    "max_bvo_residential_m2": 120000,
    "min_bvo_productive_m2": 12000,
    "max_bvo_office_m2": 9000,
    "max_bvo_horeca_m2": 3000,
    "max_bvo_cultural_m2": 3500,
    "max_bvo_social_m2": 3900,
    "max_bvo_services_combined_m2": 6500,
    "target_dwelling_count": 1630,
    "parking_spaces_total": 595,
    "plint_min_height_m": 8,
    "setback_standard_trigger_m": 21,
    "setback_standard_depth_m": 2.5,
    "max_bvo_per_floor_21_50m": 600,
    "max_bvo_per_floor_above_50m": 500,
    "source": "artikel 3.2.2 + 3.3.9",
    "note": "Hardcoded from Draka regels for prototype. In production: extracted via DSO teksten API.",
}

# Reverse maps from short code → full naam, for matching framework codes.
_SBA_BY_CODE = {v["sba_code"]: k for k, v in SBA_MODIFIERS.items()}
_DVG_BY_CODE = {f"sba-dvg{k.rsplit(' ', 1)[-1]}": k for k in DVG_THRESHOLDS}


# ---------------------------------------------------------------------
# Part A: rule attachment
# ---------------------------------------------------------------------


def attach_rules_to_zone(zone: dict) -> dict:
    out = dict(zone)

    # SGD lookup (case-insensitive on full name)
    sgd_full = zone.get("sgd_full_name", "")
    sgd_rule = None
    if sgd_full:
        for naam, rule in SGD_RULES.items():
            if naam.lower() == sgd_full.lower():
                sgd_rule = rule
                break
    out["sgd_rule"] = sgd_rule

    # SBA + DVG lookup by short codes already on the framework
    sba_rules = []
    for code in zone.get("sba_codes", []):
        full_naam = _SBA_BY_CODE.get(code)
        if full_naam:
            sba_rules.append({"code": code, "naam": full_naam, **SBA_MODIFIERS[full_naam]})
    out["sba_rules"] = sba_rules

    dvg_rules = []
    for code in zone.get("acoustic_overlays", []):
        full_naam = _DVG_BY_CODE.get(code)
        if full_naam:
            dvg_rules.append({"code": code, "naam": full_naam, **DVG_THRESHOLDS[full_naam]})
    out["dvg_rules"] = dvg_rules

    # Merge: sba overrides sgd for setback_trigger_m and floor_plate_cap_exempt
    setback_trigger = sgd_rule["setback_trigger_m"] if sgd_rule else None
    setback_depth = sgd_rule["setback_depth_m"] if sgd_rule else None
    floor_plate_exempt = sgd_rule["floor_plate_cap_exempt"] if sgd_rule else False
    for sba in sba_rules:
        if "setback_trigger_m" in sba:
            setback_trigger = sba["setback_trigger_m"]
        if sba.get("floor_plate_cap_exempt") is True:
            floor_plate_exempt = True

    out["effective"] = {
        "setback_trigger_m": setback_trigger,
        "setback_depth_m": setback_depth,
        "floor_plate_cap_exempt": floor_plate_exempt,
        "allows_wonen": sgd_rule["allows_wonen"] if sgd_rule else None,
        "productive_required_first_m2": sgd_rule["productive_required_first_m2"]
        if sgd_rule
        else None,
        "horeca_dienstverlening_cultuur_max_m2": sgd_rule["horeca_dienstverlening_cultuur_max_m2"]
        if sgd_rule
        else None,
        "dvg_thresholds_m": [d["threshold_m"] for d in dvg_rules],
    }
    return out


# ---------------------------------------------------------------------
# Overlay polygons from GML (for parameters JSON)
# ---------------------------------------------------------------------


def parse_poslist(text: str) -> list[tuple[float, float]]:
    nums = [float(x) for x in text.strip().split()]
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums), 2)]


def _first_poly(el) -> list[tuple[float, float]] | None:
    pos = el.find(f".//{GML}posList")
    if pos is None or not pos.text:
        return None
    coords = parse_poslist(pos.text)
    return coords if len(coords) >= 3 else None


def _to_wgs84(rd: list[tuple[float, float]]) -> list[list[float]]:
    return [list(_to_wgs.transform(x, y)) for x, y in rd]


def extract_overlay_zones(root) -> list[dict]:
    out = []
    for tag, kind in [
        ("Dubbelbestemming", "dubbelbestemming"),
        ("Gebiedsaanduiding", "gebiedsaanduiding"),
    ]:
        for el in root.iter(f"{IMRO}{tag}"):
            naam_el = el.find(f"{IMRO}naam")
            naam = naam_el.text.strip() if naam_el is not None and naam_el.text else ""
            coords = _first_poly(el)
            if not coords:
                continue
            out.append(
                {
                    "type": kind,
                    "naam": naam,
                    "polygon_wgs84": [
                        [round(lon, 8), round(lat, 8)] for lon, lat in _to_wgs84(coords)
                    ],
                }
            )
    return out


# ---------------------------------------------------------------------
# Part C: GeoJSON
# ---------------------------------------------------------------------


def build_geojson(framework: dict) -> dict:
    features = []

    # site boundary
    if framework.get("site_boundary_wgs84"):
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [framework["site_boundary_wgs84"]],
                },
                "properties": {
                    "object_type": "site_boundary",
                    "plan_id": framework.get("plan_id"),
                },
            }
        )

    # bouwvlakken
    for z in framework["zones"]:
        props = {k: v for k, v in z.items() if k not in ("polygon_rd", "polygon_wgs84")}
        props["object_type"] = "bouwvlak"
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [z["polygon_wgs84"]]},
                "properties": props,
            }
        )

    # no-build zones
    for nb in framework.get("no_build_zones", []):
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [nb["polygon_wgs84"]]},
                "properties": {
                    "object_type": "no_build",
                    "sub_type": nb["type"],
                    "naam": nb["naam"],
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------
# Part D: OBJ export
# ---------------------------------------------------------------------


def _safe_group(name: str) -> str:
    return name.replace(" ", "_").replace("/", "_") or "zone"


def build_obj(framework: dict) -> str:
    # site centroid (RD) as origin
    boundary = framework.get("site_boundary_rd") or []
    if boundary:
        cx, cy = Polygon(boundary).centroid.coords[0]
    else:
        cx = cy = 0.0

    lines = [
        "# Draka bouwvlakken extruded to max_height_m",
        "# Coordinates in metres, localised to site centroid",
        f"# Origin (RD): {cx:.3f} {cy:.3f}",
    ]
    vi = 1  # OBJ vertex index (1-based)

    def emit_extrusion(group: str, poly_rd: list[list[float]], height: float):
        nonlocal vi
        # drop closing duplicate vertex if present
        ring = poly_rd[:-1] if len(poly_rd) > 1 and poly_rd[0] == poly_rd[-1] else poly_rd
        n = len(ring)
        if n < 3:
            return
        lines.append(f"g {group}")
        # bottom verts (z=0) then top verts (z=h)
        for x, y in ring:
            lines.append(f"v {x - cx:.3f} {y - cy:.3f} 0.0")
        for x, y in ring:
            lines.append(f"v {x - cx:.3f} {y - cy:.3f} {height:.3f}")
        base = vi
        # bottom face (reversed for outward normal)
        bottom = [base + i for i in range(n)]
        lines.append("f " + " ".join(str(i) for i in reversed(bottom)))
        # top face
        top = [base + n + i for i in range(n)]
        lines.append("f " + " ".join(str(i) for i in top))
        # side faces
        for i in range(n):
            j = (i + 1) % n
            a, b = base + i, base + j
            c, d = base + n + j, base + n + i
            lines.append(f"f {a} {b} {c} {d}")
        vi += 2 * n

    for z in framework["zones"]:
        h = z.get("max_height_m") or 0.0
        if h <= 0:
            continue
        label = z.get("sgd_code") or (",".join(z.get("sba_codes", [])) or f"zone-{z['zone_index']}")
        group = f"{_safe_group(label)}_h{h:g}m"
        emit_extrusion(group, z["polygon_rd"], h)

    # no-build zones as flat polygons at z=0
    for nb in framework.get("no_build_zones", []):
        poly_rd = nb.get("polygon_rd")
        if not poly_rd:
            continue
        label = f"nobuild_{_safe_group(nb.get('naam', 'zone'))}"
        ring = poly_rd[:-1] if len(poly_rd) > 1 and poly_rd[0] == poly_rd[-1] else poly_rd
        n = len(ring)
        if n < 3:
            continue
        lines.append(f"g {label}")
        for x, y in ring:
            lines.append(f"v {x - cx:.3f} {y - cy:.3f} 0.0")
        lines.append("f " + " ".join(str(vi + i) for i in range(n)))
        vi += n

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------


def main() -> None:
    framework = json.loads(FRAMEWORK_IN.read_text())

    # Part A
    framework["zones"] = [attach_rules_to_zone(z) for z in framework["zones"]]
    FRAMEWORK_OUT.write_text(json.dumps(framework, indent=2))
    print(f"Wrote {FRAMEWORK_OUT}")

    # site area (RD)
    site_area = None
    if framework.get("site_boundary_rd"):
        site_area = round(Polygon(framework["site_boundary_rd"]).area, 2)

    # overlay zones from GML
    root = etree.fromstring(GML_CACHE.read_bytes())
    overlay_zones = extract_overlay_zones(root)

    # Part B
    params = {
        "plan_id": framework.get("plan_id"),
        "approach": "gml_authoritative",
        "prototype_note": "Programme rules hardcoded from regels for demo. Heights and geometry from GML.",
        "generated_at": datetime.now(UTC).isoformat(),
        "crs_rd": framework.get("crs_rd"),
        "crs_wgs84": framework.get("crs_wgs84"),
        "site_boundary_rd": framework.get("site_boundary_rd"),
        "site_boundary_wgs84": framework.get("site_boundary_wgs84"),
        "site_area_m2": site_area,
        "site_constraints": SITE_CONSTRAINTS,
        "zones": framework["zones"],
        "no_build_zones": framework.get("no_build_zones", []),
        "overlay_zones": overlay_zones,
    }
    PARAMS_OUT.write_text(json.dumps(params, indent=2))
    print(f"Wrote {PARAMS_OUT}")

    # Part C
    GEOJSON_OUT.write_text(json.dumps(build_geojson(framework), indent=2))
    print(f"Wrote {GEOJSON_OUT}")

    # Part D
    OBJ_OUT.write_text(build_obj(framework))
    print(f"Wrote {OBJ_OUT}")

    # quick summary
    print()
    print(
        f"{'zone':>4} | {'sgd':>6} | {'h':>5} | wonen | prod_req | hdc_max | floor_exempt | setback"
    )
    print("-" * 90)
    for z in framework["zones"]:
        eff = z["effective"]
        print(
            f"{z['zone_index']:>4} | "
            f"{z['sgd_code'] or '-':>6} | "
            f"{(z['max_height_m'] or 0):>5.1f} | "
            f"{eff['allows_wonen']!s:>5} | "
            f"{eff['productive_required_first_m2']!s:>8} | "
            f"{eff['horeca_dienstverlening_cultuur_max_m2']!s:>7} | "
            f"{eff['floor_plate_cap_exempt']!s:>12} | "
            f"{eff['setback_trigger_m']}m/{eff['setback_depth_m']}m"
        )


if __name__ == "__main__":
    main()
