"""Cross-document validation and universal sanity bounds.

Layers 4 and 5 of the Scenario 1 defence. Operates on a populated
ParametricFramework and returns a list of ValidationFinding objects
(disagreements, out-of-bounds values) without modifying the framework.
The viewer surfaces findings; the PM resolves.

Primary functions:
    check_cross_doc_consistency(framework) -> list[ValidationFinding]
    check_sanity_bounds(framework) -> list[ValidationFinding]
    run_all_validations(framework) -> list[ValidationFinding]

Cross-doc consistency: when the same value is mentioned multiple times
in different documents with different numbers, flag with
'cross_doc_conflict'.

Universal sanity bounds (per CLAUDE.md, universal physical sense only):
    height            : 3 m  .. 200 m
    parking ratio     : 0    .. 4 per dwelling
    setback           : 0 m  .. 50 m
    FSI/FAR           : 0    .. 8
    gfa per project   : 100 m^2 .. 1,000,000 m^2

These bounds are universal, not municipality-specific.

Stage 2 and later (validators run after extraction merges).
"""

from __future__ import annotations

# TODO: implement validators
