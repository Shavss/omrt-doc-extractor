# Grasshopper handoff

This folder holds artifacts for the Grasshopper engineer consuming the JSON output of the pipeline.

Contents (to be populated as the prototype matures):

- `json_format.md`: documentation of the framework.json output structure (a pointer to `docs/schema_reference.md` plus consumption tips).
- `sample.gh` (optional): a minimal Grasshopper definition demonstrating consumption of the JSON.
- `userobject_proposal.md` (optional): proposed structure for a reusable GH UserObject if the integration deepens.

The actual generated handoff per project lives in `data/outputs/<project_name>/`, not here.
