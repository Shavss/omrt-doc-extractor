"""IMRO API cross-validation: Scenario 1 defence, Layer 4b.

For Dutch projects with a published plan_id matching the IMRO pattern,
queries the Ruimtelijke Plannen API v4 and compares every extracted
NumericalConstraint against the authoritative value within the configured
relative tolerance (default 5%).

Primary function:
    cross_validate_imro(framework) -> ParametricFramework

Returns a new framework with cross_validation populated on every
NumericalConstraint that has an authoritative equivalent. Confidence
flags are also updated: 'imro_api_agreement' on match, 'imro_api_disagreement'
on mismatch (with score reduced by 0.3, clipped to 0).

API endpoint:
    https://ruimte.omgevingswet.overheid.nl/ruimtelijke-plannen/api/opvragen/v4/

Graceful degradation:
- No plan_id           -> every constraint gets agreement='not_attempted'
- API unreachable      -> every constraint gets agreement='not_attempted' with network error note
- Field cannot match   -> agreement='unverifiable' with brief note
- Match within tol     -> agreement='agreement'
- Match outside tol    -> agreement='disagreement', viewer surfaces both

Stage 4b of the build plan. This is the strongest layer of the Scenario 1
defence; see docs/architecture.md section 'The Scenario 1 defence'.
"""

from __future__ import annotations

# TODO Stage 4b: implement cross_validate_imro
