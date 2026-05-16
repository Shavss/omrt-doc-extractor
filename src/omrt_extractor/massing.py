"""Example massing generation: two illustrative variants per project.

Purpose: demonstrate that the framework's numerical and geometric inputs
translate to geometry. NOT optimised design; that is the OMRT Run system's
job and lives downstream of this prototype.

Primary function:
    generate_example_massings(framework) -> list[Massing]

Two variants always produced:
    Variant A "Maximum envelope"
        Extrude every bouwvlak to its max allowed height with no setbacks.
    Variant B "Compliant with setbacks"
        Apply setback rules above the threshold height (read from the
        framework's constraints, never hardcoded).

Each Massing object includes:
    rationale: 1-2 sentences citing the rule that drove each form decision
    provenance: which inputs drove which moves
    moves: list of MassingMove with driven_by constraint IDs (validated)
    geometry_file: path to the COMPAS Mesh JSON

Shapely for 2D polygon operations, COMPAS Mesh for 3D output. Render in
viewer/streamlit_app.py with plotly Mesh3d alongside 3D BAG context buildings.

If any input the massing depends on has confidence below threshold, the
viewer displays a "preview based on unverified inputs" banner over the
visualisation.

Stage 6b of the build plan.
"""

from __future__ import annotations

# TODO Stage 6b: implement generate_example_massings
