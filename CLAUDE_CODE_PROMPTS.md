# Claude Code Prompts — GML Approach + Comparison
# Run these prompts sequentially in Claude Code.
# Each prompt is self-contained. Paste one at a time.

---

## CONTEXT (read before starting)

We have two approaches to producing parametric design inputs for the Draka Terrein
Hamerkwartier site (NL.IMRO.0363.N2102BPGST-VG01):

**Approach 1 (PDF-based, already done):**
- Source: kaveltekening PDF → geometry.json (bouwvlakken in PDF coordinate space)
- Source: regels/toelichting PDFs → programme.json (programme numbers)
- Limitation: coordinates are in PDF space (not georeferenced), zone-programme
  association is incomplete, heights have mis-assignments

**Approach 2 (GML-based, to build now):**
- Source: GML file cached at data/cache/NL.IMRO.0363.N2102BPGST-VG01.gml
- Authoritative spatial data in RD New (EPSG:28992), georeferenced
- Heights from maatvoeringen spatial join (already validated)
- Programme zones from functieaanduidingen (sgd-1 to sgd-9)
- Programme rules from regels (already extracted in programme.json)

**Goal:** Build approach 2, associate programme with each plot, then compare both.

**DO NOT delete any existing files in data/outputs/. Add approach 2 outputs to
data/outputs/approach_gml/ and comparison to data/outputs/comparison/**

---

## PROMPT 1 — Build the authoritative zone framework from GML

```
I have a bestemmingsplan GML file cached at:
  data/cache/NL.IMRO.0363.N2102BPGST-VG01.gml

The GML uses namespace http://www.geonovum.nl/imro/2012/1.1 and
GML namespace http://www.opengis.net/gml/3.2

Write and run a Python script at scripts/gml_zone_framework.py that:

1. Parses the GML and extracts these objects:

   a) PLANGEBIED — the site boundary polygon (Bestemmingsplangebied element)
      → store as polygon_rd (RD New coords) and polygon_wgs84 (converted)

   b) BOUWVLAKKEN — 8 buildable zone polygons (Bouwvlak elements)
      Each bouwvlak links to a bestemmingsvlak via xlink:href.
      For each bouwvlak:
      - Extract polygon coordinates (from gml:posList)
      - Compute area_m2 using shapely
      - Spatial join with Maatvoering label points (gml:pos inside maatvoeringInfo)
        to find max_height_m (take the maximum where waardeType contains 'bouwhoogte')
      - Store polygon in both RD New and WGS84

   c) FUNCTIEAANDUIDINGEN — programme zone polygons (Functieaanduiding elements)
      Each has a naam (e.g. 'specifieke vorm van gemengd - 2') and links to a
      bestemmingsvlak via xlink:href.
      Spatial join each functieaanduiding to its bouwvlak using the bestemmingsvlak
      href as the linking key (bouwvlak.bestemmingsvlak == functieaanduiding.bestemmingsvlak)

   d) BOUWAANDUIDINGEN — building modifier polygons (Bouwaanduiding elements)
      Spatial join to bouwvlakken by intersection.
      Normalise names:
        'specifieke bouwaanduiding - dove gevel N' → 'sba-dvgN'
        'specifieke bouwaanduiding - N' → 'sba-N'
      Mark sba-dvg* as acoustic overlays (not building zone boundaries).

   e) ENKELBESTEMMINGEN — land use zones (Enkelbestemming elements)
      Includes Gemengd (artikel 3), Groen (artikel 4), Verkeer (artikel 5).
      Groen and Verkeer are no-build zones.

   f) DUBBELBESTEMMINGEN + GEBIEDSAANDUIDINGEN — overlays
      Waarde-Archeologie (WR-A), vrijwaringszone-vaarweg, geluidzone-industrie

2. Assembles a zone framework: one entry per bouwvlak with:
   {
     "zone_index": int,               # 1-8
     "bouwvlak_id": str,              # GML id (short)
     "bestemmingsvlak_id": str,       # linked bestemmingsvlak id
     "sgd_code": str,                 # e.g. "sgd-2" (from functieaanduiding naam)
     "sgd_full_name": str,            # e.g. "specifieke vorm van gemengd - 2"
     "max_height_m": float,           # from maatvoering spatial join
     "all_heights_m": [float],        # all heights found in zone
     "footprint_area_m2": float,
     "sba_codes": [str],              # building modifiers (excluding sba-dvg)
     "acoustic_overlays": [str],      # sba-dvg codes only
     "overlaps_wra": bool,            # intersects Waarde-Archeologie?
     "overlaps_geluidzone": bool,     # intersects geluidzone-industrie?
     "polygon_rd": [[x,y]],           # RD New coordinates
     "polygon_wgs84": [[lon,lat]],    # WGS84 coordinates
   }

3. Also outputs:
   - site_boundary_rd: [[x,y]] (plangebied polygon)
   - site_boundary_wgs84: [[lon,lat]]
   - no_build_zones: list of {type, naam, polygon_wgs84}
     (Groen, Verkeer, vrijwaringszone-vaarweg)

4. Writes output to data/outputs/approach_gml/zone_framework.json
   Creates the directory if needed.

5. Prints a summary table:
   zone_index | sgd_code | max_height_m | area_m2 | sba_codes | acoustic_overlays

Use pyproj for RD New → WGS84 conversion (EPSG:28992 → EPSG:4326, always_xy=True).
Use shapely for polygon operations.
The GML file is already cached — do not re-download it.
```

---

## PROMPT 2 — Associate programme rules with each zone

```
We now have data/outputs/approach_gml/zone_framework.json with 8 bouwvlakken,
each with a sgd_code (sgd-1 through sgd-9, plus maatschappelijk).

We also have data/outputs/programme.json with site-level programme numbers.

Write and run a Python script at scripts/gml_associate_programme.py that:

1. Reads data/outputs/approach_gml/zone_framework.json

2. Defines a programme rules table (hard-coded from the bestemmingsplan regels
   we already extracted). Map each sgd_code to its rules:

   sgd-1: {
     "horeca_dienstverlening_cultuur_max_m2": 4000,
     "allows_wonen": true,
     "productive_required_first_m2": null,
     "floor_plate_cap_exempt": false,
     "setback_trigger_m": 21,
     "setback_depth_m": 2.5,
     "notes": "Standard mixed zone along Gedempt Hamerkanaal"
   }
   sgd-2: {
     "horeca_dienstverlening_cultuur_max_m2": 4000,
     "allows_wonen": true,
     "productive_required_first_m2": 2000,
     "floor_plate_cap_exempt": false,
     "setback_trigger_m": 21,
     "setback_depth_m": 2.5,
     "notes": "Woningen only after 2000m2 productive bedrijvigheid committed"
   }
   sgd-3: {
     "horeca_dienstverlening_cultuur_max_m2": 4000,
     "allows_wonen": true,
     "productive_required_first_m2": 2000,
     "floor_plate_cap_exempt": false,
     "setback_trigger_m": 21,
     "setback_depth_m": 2.5,
     "office_cap_per_building_m2": null,  # sgd-3 exempt from 2000m2 office cap
     "notes": "Same as sgd-2. Office floor-size cap does not apply here."
   }
   sgd-4: {
     "horeca_dienstverlening_cultuur_max_m2": 4000,
     "allows_wonen": true,
     "productive_required_first_m2": 1000,
     "floor_plate_cap_exempt": true,      # KEY: no 600/500m2 per floor limit
     "setback_trigger_m": 21,
     "setback_depth_m": 2.5,
     "notes": "Exempt from max bvo per bouwlaag. Larger floorplates allowed."
   }
   sgd-5: {
     "horeca_dienstverlening_cultuur_max_m2": 1500,
     "allows_wonen": false,
     "productive_required_first_m2": null,
     "floor_plate_cap_exempt": false,
     "setback_trigger_m": 21,
     "setback_depth_m": 2.5,
     "notes": "No wonen. Smaller horeca/cultuur cap."
   }
   sgd-6: {
     "horeca_dienstverlening_cultuur_max_m2": 3000,
     "allows_wonen": true,
     "productive_required_first_m2": 3000,
     "floor_plate_cap_exempt": false,
     "setback_trigger_m": 21,
     "setback_depth_m": 2.5,
     "notes": "Highest productive bedrijvigheid requirement before wonen."
   }
   sgd-7: {
     "horeca_dienstverlening_cultuur_max_m2": 4000,
     "allows_wonen": false,
     "productive_required_first_m2": null,
     "floor_plate_cap_exempt": false,
     "setback_trigger_m": 21,
     "setback_depth_m": 2.5,
     "notes": "Productieve bedrijvigheid NOT permitted. No wonen."
   }
   sgd-8: {
     "horeca_dienstverlening_cultuur_max_m2": 4000,
     "allows_wonen": false,
     "productive_required_first_m2": null,
     "floor_plate_cap_exempt": false,
     "setback_trigger_m": 21,
     "setback_depth_m": 2.5,
     "notes": "Productieve bedrijvigheid NOT permitted. No wonen."
   }
   sgd-9: {
     "horeca_dienstverlening_cultuur_max_m2": null,
     "allows_wonen": false,
     "productive_required_first_m2": null,
     "floor_plate_cap_exempt": false,
     "setback_trigger_m": 21,
     "setback_depth_m": 2.5,
     "notes": "Beeldbepalend object. Existing main form and position must be retained."
   }
   maatschappelijk: {
     "horeca_dienstverlening_cultuur_max_m2": null,
     "allows_wonen": false,
     "productive_required_first_m2": null,
     "floor_plate_cap_exempt": false,
     "setback_trigger_m": 21,
     "setback_depth_m": 2.5,
     "notes": "School zone. Min 1250m2 school footprint, min 1600m2 schoolplein+pocketpark."
   }

   Also define sba_rules:
   sba-1: setback_trigger_m=30.5 (overrides default 21m)
   sba-2: setback_trigger_m=21, standard
   sba-3: setback_trigger_m=30.5 (same as sba-1)
   sba-4: floor_plate_cap_exempt=true (no 600/500m2 per floor limit)

3. Also define site-level constraints from the regels:
   {
     "max_bvo_per_floor_highrise_21_50m": 600,  # m2, unless sba-4 or sgd-4
     "max_bvo_per_floor_highrise_above_50m": 500,
     "plint_min_height_m": 8,
     "plint_max_layers": 1,
     "setback_standard_trigger_m": 21,
     "setback_standard_depth_m": 2.5,
     "underground_parking_only": true,
     "car_access_only_via": "Gedempt Hamerkanaal",
     "green_coverage_min_pct": 40,
     "water_retention_min_mm": 60,
   }

4. Merges sgd programme rules and sba modifier rules into each zone entry,
   resolving conflicts (sba-4 overrides floor_plate_cap_exempt for example).

5. Adds programme_allocation: a suggested BVO split for each zone based on
   the sgd code and the site-level programme from programme.json.
   Distribute the 151,400m2 total across zones proportionally to footprint_area_m2,
   but respect allows_wonen and productive_required_first_m2 constraints.
   This is an indicative allocation, not binding — flag it as estimated.

6. Writes the enriched zone framework to:
   data/outputs/approach_gml/zone_framework_with_programme.json

7. Prints per zone:
   zone | sgd | height | area | allows_wonen | productive_req | floor_cap_exempt | est_bvo
```

---

## PROMPT 3 — Build GeoJSON for Grasshopper

```
Read data/outputs/approach_gml/zone_framework_with_programme.json and
write a script at scripts/gml_to_grasshopper.py that produces two outputs:

OUTPUT A: data/outputs/approach_gml/draka_grasshopper.geojson
A GeoJSON FeatureCollection in WGS84 (EPSG:4326) where each Feature is one zone.
Properties on each feature must include every field from zone_framework_with_programme.json
EXCEPT polygon_rd (keep polygon_wgs84 as the geometry).
Also include the site boundary and no-build zones as separate features with
object_type = "site_boundary" and "no_build_zone".
This file is directly openable in the Heron GH plugin.

OUTPUT B: data/outputs/approach_gml/draka_parameters.json
A flat parameter file the Grasshopper engineer reads via GH Python:
{
  "plan_id": "NL.IMRO.0363.N2102BPGST-VG01",
  "plan_naam": "Draka Terrein Hamerkwartier",
  "site_area_m2": <computed from plangebied polygon>,
  "site_boundary_wgs84": [...],
  "site_boundary_rd": [...],

  "site_constraints": {
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
    "parking_spaces_shared": 38,
    "plint_min_height_m": 8,
    "setback_standard_trigger_m": 21,
    "setback_standard_depth_m": 2.5,
    "max_bvo_per_floor_21_50m": 600,
    "max_bvo_per_floor_above_50m": 500,
    "tenure_split": {"sociale_huur": 0.30, "middenhuur": 0.40, "vrije_sector": 0.30},
    "green_coverage_min_pct": 40,
    "water_retention_min_mm": 60,
    "car_access_street": "Gedempt Hamerkanaal",
  },

  "zones": [
    {
      "zone_index": 1,
      "sgd_code": "sgd-2",
      "max_height_m": 70.0,
      "footprint_area_m2": 5746,
      "allows_wonen": true,
      "productive_required_first_m2": 2000,
      "floor_plate_cap_exempt": false,
      "setback_trigger_m": 21,
      "setback_depth_m": 2.5,
      "acoustic_overlays": ["sba-dvg4"],
      "dove_gevel_threshold_m": 58.5,
      "overlaps_wra": false,
      "overlaps_geluidzone": true,
      "estimated_bvo_m2": <computed>,
      "polygon_rd": [...],
      "polygon_wgs84": [...],
      "notes": "..."
    },
    ... (all 8 zones)
  ],

  "no_build_zones": [...],

  "flagged_issues": [
    {
      "zone": "sgd-2",
      "issue": "Height disagreement between PDF extraction (45m) and GML (70m). GML is authoritative.",
      "severity": "high",
      "action": "PM to confirm before Run"
    }
  ],

  "approach": "gml_authoritative",
  "generated_at": "<timestamp>"
}

The dove_gevel_threshold_m per zone should come from the acoustic overlay:
  sba-dvg1 → 21m, sba-dvg2 → 30m, sba-dvg3 → 22.5m,
  sba-dvg4 → 58.5m, sba-dvg5 → 40m
If a zone has multiple acoustic overlays, list all thresholds.

Also include a flagged_issues list with:
- The sgd-2 height disagreement (PDF=45m vs GML=70m)
- Any zone where allows_wonen=false but estimated_bvo includes residential
- Any zone where overlaps_wra=true (archaeology review required)
```

---

## PROMPT 4 — Compare approach 1 vs approach 2

```
Write and run a Python script at scripts/compare_approaches.py that produces a
side-by-side comparison of the two approaches.

APPROACH 1 inputs:
  data/outputs/geometry.json    (PDF-extracted bouwvlakken, PDF coordinate space)
  data/outputs/programme.json   (site-level programme numbers)

APPROACH 2 inputs:
  data/outputs/approach_gml/zone_framework_with_programme.json
  data/outputs/approach_gml/draka_parameters.json

The comparison should cover four dimensions:

--- DIMENSION 1: Zone count and identification ---
How many bouwvlakken did each approach find?
Which zones does approach 1 identify (by label) vs approach 2 (by sgd_code)?
Are there zones in approach 1 that have no sgd match in approach 2, or vice versa?
Output: a zone-matching table.

--- DIMENSION 2: Height comparison ---
For each matched zone pair, compare:
  approach_1_height_m | approach_2_height_m | delta_m | agreement
Use sgd_code as the join key where available, area proximity otherwise.
Flag any delta > 1m as a disagreement.

--- DIMENSION 3: Programme association ---
Approach 1: geometry.json has bestemming_codes and function_aanduidingen per zone,
but no programme rules or BVO allocation.
Approach 2: zone_framework_with_programme.json has full programme rules per zone.
For zones that appear in both, show what programme information approach 2 adds
that approach 1 was missing.

--- DIMENSION 4: Coordinate system and usability ---
Approach 1: PDF space (points × scale factor). Not georeferenced.
Approach 2: RD New (EPSG:28992) + WGS84. Georeferenced.
Compute the real-world dimensions of each approach's bouwvlakken.
For approach 1, convert using meters_per_unit=0.35277 and scale_denominator=1000
from geometry.json to get approximate real-world areas.
Compare areas between the two approaches for matched zones.

Output:
  data/outputs/comparison/approach_comparison.json  (machine-readable)
  data/outputs/comparison/approach_comparison.md    (human-readable report)

The markdown report should read like a PM handover note:
- What each approach got right
- Where they disagree and why
- Which approach to trust for each data type
- Recommended action before starting the Grasshopper Run
- One-paragraph executive summary at the top
```

---

## PROMPT 5 — Generate comparison visualisation

```
Write and run a Python script at scripts/visualise_comparison.py that produces
a single PNG at data/outputs/comparison/approach_comparison.png

The figure has three panels:

LEFT PANEL: Approach 1 zones (PDF space)
- Draw each bouwvlak polygon from geometry.json coordinates
- Colour by height_m using this scale:
    None → grey, 21m → #d4e8f7, 30.5m → #a8d1f0,
    40m → #7ab8e8, 45m → #f7c97a, 60m → #f4a44a, 70m → #e05c3a
- Label each polygon with: height_m and function_aanduidingen (if any)
- Title: "Approach 1 — PDF extraction (kaveltekening)\nCoordinates: PDF space"

CENTRE PANEL: Approach 2 zones (RD New, normalised to local origin)
- Draw each bouwvlak polygon from zone_framework_with_programme.json polygon_rd
- Colour by max_height_m using same scale
- Label each polygon with: sgd_code and max_height_m
- Title: "Approach 2 — GML authoritative\nCoordinates: RD New (metres)"

RIGHT PANEL: Height comparison bar chart
- X axis: zone labels (sgd codes where known, index otherwise)
- Two bars per zone: approach 1 height (blue) and approach 2 height (orange)
- Zones where |delta| > 1m get a red asterisk
- Title: "Height comparison\nApproach 1 (PDF) vs Approach 2 (GML)"

Below the three panels, add a text box summarising:
  Agreements: N/total | Disagreements: N | Not matched: N
  Key finding: <one sentence about the most important disagreement>

Use matplotlib. Save at 150 DPI.
Flip y-axis for approach 1 (PDF y runs top-down).
Do not import any file that does not exist — check paths before reading.
```

---

## PROMPT 6 — Write the final Grasshopper-ready summary

```
We now have both approaches compared. Write a final script at
scripts/build_final_framework.py that assembles the definitive
parametric framework for the Grasshopper engineer.

The rule for resolving conflicts between approaches:
  - GEOMETRY: always use approach 2 (GML) — it is georeferenced and authoritative
  - HEIGHTS: always use approach 2 (GML maatvoeringen) — they are the legal source
  - PROGRAMME RULES: use approach 2 (regels-derived, zone-specific)
  - PROGRAMME NUMBERS (totals): use programme.json — these are correct in both
  - FLAG: any case where approach 1 and 2 disagree on height with delta > 5m

Output: data/outputs/draka_parametric_framework.json
This is THE file the Grasshopper engineer opens. It should contain:
  - site_boundary_rd and site_boundary_wgs84
  - site_constraints (all numerical limits)
  - zones (8 entries, one per bouwvlak, with full programme + geometry)
  - no_build_zones
  - unit_mix (from programme.json)
  - flagged_issues (from comparison)
  - data_sources (list which file each field came from)
  - confidence scores per zone (from approach 2 where available)

Also write data/outputs/draka_parametric_framework.geojson
— the same data as a GeoJSON for direct import into Heron/GH.

Print a final summary:
  "PARAMETRIC FRAMEWORK READY"
  Site area: Xm2
  Buildable zones: 8
  Total max height: 70m
  Programme: 151,400m2 total / 1,630 dwellings / 595 parking
  Flagged issues: N (list them)
  Files written: (list paths)
```

---

## NOTES FOR CLAUDE CODE

- The GML is at: data/cache/NL.IMRO.0363.N2102BPGST-VG01.gml (already cached)
- Do NOT re-download anything. All source data is local.
- Required packages: lxml, shapely, pyproj, matplotlib (all installed in .venv)
- Always use Path(__file__).parent.parent to find repo root
- Always load .env with load_dotenv(Path(__file__).parent.parent / ".env")
- Namespace for GML: http://www.geonovum.nl/imro/2012/1.1
- Namespace for geometry: http://www.opengis.net/gml/3.2
- Coordinate conversion: pyproj.Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)
- Do not use pyproj.transform (deprecated) — use Transformer

## KNOWN FACTS TO ENCODE (do not re-derive these)

Height per zone from GML (authoritative):
  sgd-2 (bouwvlak adc4c5...): max 70m
  sgd-3 (bouwvlak 88a8b8...): max 60m
  sgd-4 (bouwvlak b38b9e...): max 60m
  sgd-5 (bouwvlak a5a371...): max 40m
  sgd-6/sgd-9 (bouwvlak a11212...): max 30.5m
  sgd-8 (bouwvlak b6685d...): max 30.5m
  sgd-7 (bouwvlak 925675...): max 30.5m
  sgd-1/maatschappelijk (bouwvlak 89fef2...): max 60m

Key disagreement to flag:
  sgd-2: PDF extracted 45m, GML says 70m. Delta = 25m. GML is correct.
  Likely cause: PDF extractor assigned 45m label (belonging to sba-1 zone)
  to sgd-2 polygon due to spatial proximity on the kaveltekening.

Acoustic overlay thresholds (from artikel 3.2.2):
  sba-dvg1: dove gevel required above 21m
  sba-dvg2: dove gevel required above 30m
  sba-dvg3: dove gevel required above 22.5m
  sba-dvg4: dove gevel required above 58.5m
  sba-dvg5: dove gevel required above 40m
