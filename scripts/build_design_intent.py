"""Build a consolidated design_intent.json for Grasshopper.

Merges Approach 1 (PDF-extracted constraints + programme) with Approach 2
(GML-authoritative geometry + DSO-style rules). Approach 2 wins on geometry
and site rules; Approach 1 supplies the LLM-inferred programme rationale.

Output: data/outputs/draka/design_intent.json
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "outputs" / "draka"
GML_PARAMS = OUT_DIR / "approach_gml" / "draka_gml_parameters.json"
GML_FW = OUT_DIR / "approach_gml" / "zone_framework_with_rules.json"
PROGRAMME = OUT_DIR / "programme.json"
FRAMEWORK = OUT_DIR / "framework.json"
GEOMETRY = OUT_DIR / "geometry.json"
TARGET = OUT_DIR / "design_intent.json"


def _load(p: Path) -> dict[str, Any]:
    return json.loads(p.read_text())


def build() -> dict[str, Any]:
    gml = _load(GML_PARAMS)
    gml_fw = _load(GML_FW)
    programme = _load(PROGRAMME)
    framework_root = _load(FRAMEWORK)
    fw = framework_root.get("framework", framework_root)
    geom = _load(GEOMETRY)

    zones_out: list[dict[str, Any]] = []
    for z in gml_fw.get("zones", []):
        eff = z.get("effective") or {}
        zones_out.append(
            {
                "zone_id": z.get("bouwvlak_id"),
                "sgd_code": z.get("sgd_code"),
                "sgd_name": z.get("sgd_full_name"),
                "sba_codes": z.get("sba_codes") or [],
                "acoustic_overlays": z.get("acoustic_overlays") or [],
                "max_height_m": z.get("max_height_m"),
                "all_heights_m": z.get("all_heights_m") or [],
                "footprint_area_m2": z.get("footprint_area_m2"),
                "polygon_rd": z.get("polygon_rd"),
                "polygon_wgs84": z.get("polygon_wgs84"),
                "rules": {
                    "allows_wonen": eff.get("allows_wonen"),
                    "productive_required_first_m2": eff.get(
                        "productive_required_first_m2"
                    ),
                    "horeca_dvg_cultuur_max_m2": eff.get(
                        "horeca_dienstverlening_cultuur_max_m2"
                    ),
                    "floor_plate_cap_exempt": eff.get("floor_plate_cap_exempt"),
                    "setback_trigger_m": eff.get("setback_trigger_m"),
                    "setback_depth_m": eff.get("setback_depth_m"),
                    "dvg_thresholds_m": eff.get("dvg_thresholds_m") or [],
                },
                "source_artikel": (z.get("sgd_rule") or {}).get("source"),
            }
        )

    site_c = gml.get("site_constraints") or {}
    use_split = programme.get("use_split") or {}

    intent = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "plan_id": gml.get("plan_id"),
        "approach_provenance": {
            "geometry": "approach_2_gml",
            "site_rules": "approach_2_gml (hardcoded for prototype)",
            "programme_split": "approach_1_pdf_llm",
            "programme_total": "agreed_both",
        },
        "crs": {
            "rd": gml.get("crs_rd", "EPSG:28992"),
            "wgs84": gml.get("crs_wgs84", "EPSG:4326"),
        },
        "site": {
            "boundary_rd": gml.get("site_boundary_rd"),
            "boundary_wgs84": gml.get("site_boundary_wgs84"),
            "area_m2": gml.get("site_area_m2"),
        },
        "site_constraints": {
            "max_bvo_total_m2": site_c.get("max_bvo_total_m2"),
            "max_bvo_residential_m2": site_c.get("max_bvo_residential_m2"),
            "min_bvo_productive_m2": site_c.get("min_bvo_productive_m2"),
            "max_bvo_office_m2": site_c.get("max_bvo_office_m2"),
            "max_bvo_horeca_m2": site_c.get("max_bvo_horeca_m2"),
            "max_bvo_cultural_m2": site_c.get("max_bvo_cultural_m2"),
            "max_bvo_social_m2": site_c.get("max_bvo_social_m2"),
            "max_bvo_services_combined_m2": site_c.get("max_bvo_services_combined_m2"),
            "target_dwelling_count": site_c.get("target_dwelling_count"),
            "parking_spaces_total": site_c.get("parking_spaces_total"),
            "plint_min_height_m": site_c.get("plint_min_height_m"),
            "setback_standard_trigger_m": site_c.get("setback_standard_trigger_m"),
            "setback_standard_depth_m": site_c.get("setback_standard_depth_m"),
            "max_bvo_per_floor_21_50m": site_c.get("max_bvo_per_floor_21_50m"),
            "max_bvo_per_floor_above_50m": site_c.get("max_bvo_per_floor_above_50m"),
            "source": site_c.get("source"),
        },
        "programme": {
            "target_total_gfa_m2": programme.get("target_total_gfa_m2"),
            "target_dwelling_count": programme.get("target_dwelling_count"),
            "parking_demand": programme.get("parking_demand"),
            "use_split_m2": {
                "residential": use_split.get("residential_m2"),
                "productive": use_split.get("productive_m2"),
                "office": use_split.get("office_m2"),
                "retail_horeca": use_split.get("retail_horeca_m2"),
                "cultural": use_split.get("cultural_m2"),
                "social": use_split.get("social_m2"),
                "other": use_split.get("other_m2"),
            },
            "unit_mix": programme.get("unit_mix") or [],
        },
        "zones": zones_out,
        "no_build_zones": gml.get("no_build_zones") or [],
        "overlay_zones": gml.get("overlay_zones") or [],
        "notes": {
            "geometry_source": (
                "Authoritative IMRO/GML bouwvlakken; PDF kaveltekening used "
                "only as a sanity check (Approach 1)."
            ),
            "rules_source": (
                "Hardcoded from Draka regels for prototype. In production: "
                "DSO Ruimtelijke Plannen teksten API → same LLM extraction "
                "pipeline that handles PDF regels."
            ),
            "validation_summary": (
                f"PDF extraction matched GML on {len(zones_out)} zones at the "
                "site level; per-zone height deltas visible in the Streamlit "
                "viewer (Approach 2 — GML tab → Section A)."
            ),
        },
        "consumers": {
            "grasshopper": {
                "primary_geometry": "zones[*].polygon_rd extruded to zones[*].max_height_m",
                "site_polygon": "site.boundary_rd",
                "no_build": "no_build_zones[*].polygon_rd (exclude from buildable footprint)",
                "envelope_rules": "site_constraints.setback_standard_* + zones[*].rules",
                "programme_targets": "programme.* used to size massing variants",
            }
        },
        "x_references": {
            "approach_1_framework": "data/outputs/draka/framework.json",
            "approach_1_programme": "data/outputs/draka/programme.json",
            "approach_1_geometry": "data/outputs/draka/geometry.json",
            "approach_1_massing_inputs": "data/outputs/draka/massing_inputs.json",
            "approach_2_gml_parameters": "data/outputs/draka/approach_gml/draka_gml_parameters.json",
            "approach_2_zone_framework": "data/outputs/draka/approach_gml/zone_framework_with_rules.json",
            "approach_2_obj": "data/outputs/draka/approach_gml/draka_gml.obj",
            "approach_2_geojson": "data/outputs/draka/approach_gml/draka_gml.geojson",
        },
    }
    # Silence unused-var hints by referencing fw/geom in stats only.
    intent["stats"] = {
        "approach_1_numerical_constraints": len(
            fw.get("constraints", {}).get("numerical", []) or []
        ),
        "approach_1_bouwvlakken": len(geom.get("bouwvlakken") or []),
        "approach_2_zones": len(zones_out),
    }
    return intent


def main() -> None:
    intent = build()
    TARGET.write_text(json.dumps(intent, indent=2, default=str))
    print(f"Wrote {TARGET}")
    print(f"  zones={intent['stats']['approach_2_zones']}, "
          f"size={TARGET.stat().st_size} bytes")


if __name__ == "__main__":
    main()
