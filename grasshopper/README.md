# Grasshopper handoff

JSON + COMPAS geometry artifacts the Grasshopper engineer consumes downstream of
the extraction pipeline.

The pipeline currently produces two parallel approaches. **Approach 1** (PDF-only)
is the general-purpose path that runs on any Dutch zoning packet. **Approach 2**
(GML-authoritative) is a project-specific overlay that only runs when a
bestemmingsplan GML is available (currently Draka only).

## Where the live artifacts live

For each project, the pipeline writes everything to `data/outputs/<project_name>/`.
The Grasshopper consumer reads from there. This `grasshopper/` folder holds a
**reference copy** of the Draka run plus the README you're reading.

## What Grasshopper reads — Approach 1 (PDF)

Primary input:

- `framework.json` — the full `ParametricFramework`: site, constraints, zones,
  geometry refs, programme, provenance. This is the canonical handoff. See
  `docs/schema_reference.md` for field-by-field documentation.

Companions referenced from `framework.json`:

- `geometry/*.compas` — per-zone polygons (bouwvlakken, no-build zones,
  dvg overlays, plot boundary) as COMPAS-JSON.
- `massings/variant_a_maximum_envelope.compas.json` + `.obj` — maximum-envelope
  massing per zone.
- `massings/variant_b_compliant_with_setbacks.compas.json` + `.obj` —
  setback-compliant variant.
- `massing_inputs.json` — slim numeric envelope (heights, footprints, setback
  triggers) for engineers who don't want to parse the full framework.
- `geometry.json` — flat geometry-only view for quick inspection.

**Coordinate space:** PDF coordinates (not georeferenced). Convert with
`meters_per_unit = 0.35277` and `scale_denominator = 1000` if you need metres.

## What Grasshopper reads — Approach 2 (GML, project-specific)

Only produced when the project has a bestemmingsplan GML cached and the
`scripts/gml_*.py` chain is run.

- `draka_gml_parameters.json` — flat parameter file: site constraints, zones
  with sgd codes, heights from maatvoeringen, programme rules per zone,
  flagged_issues. Designed to be read directly from GH Python.
- `draka_gml.geojson` — GeoJSON FeatureCollection in WGS84 (EPSG:4326), openable
  by the Heron GH plugin.
- `draka_gml.obj` — extruded zones as OBJ.
- `zone_framework_gml.json` — intermediate zone framework before programme join.
- `zone_framework_with_rules.json` — zone framework after programme rules join.

**Coordinate space:** RD New (EPSG:28992) + WGS84. Georeferenced.

## Reference example: Draka

`examples/draka/` is a snapshot of the Draka Terrein Hamerkwartier outputs
(IMRO ID `NL.IMRO.0363.N2102BPGST-VG01`):

```
examples/draka/
├── approach_1_pdf/         # PDF pipeline output
│   ├── framework.json
│   ├── massing_inputs.json
│   ├── geometry.json
│   ├── geometry/           # *.compas per zone
│   └── massings/           # variant_a + variant_b
└── approach_2_gml/         # GML-authoritative output
    ├── draka_gml_parameters.json
    ├── draka_gml.geojson
    ├── draka_gml.obj
    ├── zone_framework_gml.json
    └── zone_framework_with_rules.json
```

## Adding a new test project

New projects run Approach 1 only.

```bash
# 1. Run the pipeline
omrt run data/inputs/<project_name>/

# 2. Copy the handoff into this folder for the GH engineer
python scripts/copy_to_grasshopper.py <project_name>
```

This populates `grasshopper/examples/<project_name>/approach_1_pdf/` with the
same layout as the Draka example.

## Verification status

Every numeric value in `framework.json` carries a `Provenance` (document, page,
quoted text) and `Confidence` (0.0–1.0). The Grasshopper definition should
respect the `verification_status` banner and surface low-confidence fields to
the human reviewer before they drive geometry.
