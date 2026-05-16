"""Grasshopper handoff serialisation.

Writes the validated ParametricFramework to the format the Grasshopper
engineer consumes. Three artifacts per project under
data/outputs/<project_name>/:

    framework.json       The full ParametricFramework
    geometry/*.compas    COMPAS Mesh JSON per GeometricConstraint and Massing
    summary.md           Human-readable summary for the GH engineer

Primary function:
    write_grasshopper_handoff(framework, output_dir) -> Path

The summary.md is generated from the framework and lists every binding
constraint with its provenance, the programme proposal with reasoning,
and any IMRO cross-validation disagreements at the top so the engineer
sees them first.

JSON output header always carries verification_status. Until the framework
is marked 'reviewed', the header reads "PROTOTYPE OUTPUT, NOT VERIFIED".

Stage 6 of the build plan.
"""

from __future__ import annotations

# TODO Stage 6: implement write_grasshopper_handoff
