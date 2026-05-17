"""Reconcile bouwvlak heights against regels height constraints.

Polygons get heights via spatial proximity to height labels in the
kaveltekening; that's brittle. The regels carry a verbatim clause stating
the maximum bouwhoogte per aanduiding and are authoritative. This module
overrides verbeelding-derived heights with regels-derived heights where
the two disagree, and records the change for audit.

The matching is purely string-based: each NumericalConstraint with
category 'height' and is_maximum=True declares the aanduiding labels it
binds on via `applies_to`. We normalise both sides (lowercase, strip
brackets, '-' -> '_') so 'sba-1', 'sba_1', '[sba-1]' and 'SBA-1' all
match. No municipality- or document-specific values are hardcoded.
"""

from __future__ import annotations

from typing import Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from omrt_extractor.constraint_filters import is_base_height_constraint
from omrt_extractor.geometry import Geometry, LabeledPolygon
from omrt_extractor.schemas import (
    NumericalConstraint,
    ParametricFramework,
    Provenance,
)

HEIGHT_MATCH_TOLERANCE_M = 0.5


ReconciliationAction = Literal[
    "inferred", "matched", "corrected", "unmatched", "skipped_non_base"
]


# Tokens that flag a condition as a permit-gated upward deviation: the
# value describes a higher max attainable only with an extra approval,
# not the base max for the zone. Lowercase; matched as substrings against
# a lowercased condition string. Dutch and English tokens both included.
_PERMIT_DEVIATION_TOKENS: tuple[str, ...] = (
    "afwijken",
    "afwijking",
    "verhoogd",
    "verhoging",
    "omgevingsvergunning",
    "ontheffing",
    "binnenplanse",
    "deviation",
    "increase",
    "increased",
    "exception",
    "with permit",
)

# Tokens that flag a condition as a stipulation on how the same value is
# interpreted (e.g. "average over all heights"). The value itself is the
# base max; reconciliation should use it.
_STIPULATION_TOKENS: tuple[str, ...] = (
    "gemiddelde",
    "geldt als",
    "gemeten",
    "average",
    "interpreted as",
    "measured",
)


def _is_permit_gated_deviation(condition: str | None) -> bool:
    """True if the condition describes a permit-gated upward deviation.

    Such conditions name a higher max attainable only with an extra
    approval and must not override the base height of a polygon.
    Stipulations on the same value (e.g. "gemiddelde over alle
    bouwhoogtes") are NOT deviations and return False.

    Heuristic, in priority order:
      - empty/None condition -> False
      - any permit token present -> True
      - any pure-stipulation token present (and no permit token) -> False
      - otherwise -> True (conservative: when in doubt, skip)
    """
    if not condition:
        return False
    c = condition.lower()
    if any(tok in c for tok in _PERMIT_DEVIATION_TOKENS):
        return True
    if any(tok in c for tok in _STIPULATION_TOKENS):
        return False
    return True


class ReconciliationFinding(BaseModel):
    """One audit record from the height-reconciliation pass.

    - inferred:  polygon had no height; regels value adopted.
    - matched:   polygon height already agreed with regels (within tolerance).
    - corrected: polygon height differed from regels; overwritten with regels value.
    - unmatched: regels constraint references a label that no polygon carries.
    """

    model_config = ConfigDict(extra="forbid")

    polygon_index: int  # -1 when action='unmatched' or 'skipped_non_base'
    label: str
    action: ReconciliationAction
    previous_height_m: float | None
    new_height_m: float
    source_constraint_id: str
    source_constraint_provenance: Provenance
    non_base_height_constraints_skipped: list[str] = Field(default_factory=list)


def _normalise_label(s: str) -> str:
    """Lowercase, strip wrapping brackets/parens, '-' -> '_'.

    Generic IMRO-style normalisation, not value-specific.
    """
    t = s.strip()
    if len(t) >= 2 and t[0] in "([" and t[-1] in ")]":
        t = t[1:-1].strip()
    return t.lower().replace("-", "_").replace(" ", "_")


def _polygon_labels(p: LabeledPolygon) -> set[str]:
    """All aanduiding labels carried by a polygon, normalised."""
    return {
        _normalise_label(s)
        for s in (*p.bouwaanduidingen, *p.function_aanduidingen)
    }


def _pick_winner(
    candidates: list[NumericalConstraint],
) -> NumericalConstraint:
    """Highest confidence; ties broken by absence of a `condition`."""
    return max(
        candidates,
        key=lambda c: (c.confidence.score, c.condition is None),
    )


def reconcile_heights(
    framework: ParametricFramework,
    geometry: Geometry,
) -> tuple[Geometry, list[ReconciliationFinding]]:
    """Reconcile bouwvlak heights against regels height constraints.

    For each height NumericalConstraint with is_maximum=True and at least
    one label in `applies_to`, find all polygons in geometry.bouwvlakken
    whose bouwaanduidingen or function_aanduidingen normalise to the same
    label.

    - polygon.height_m None       -> set to constraint.value (INFERRED)
    - within HEIGHT_MATCH_TOLERANCE_M -> leave (MATCHED)
    - differs                     -> overwrite, log CORRECTED (60->45)

    The regels value wins because it carries a verbatim quote from a
    binding document; the verbeelding height was inferred by spatial
    proximity.

    When a constraint has multiple labels in `applies_to`, each label is
    processed independently. When several constraints match the same
    (polygon, label) pair, the highest-confidence one wins, with base
    rules (no condition) preferred over deviation rules on ties.

    Constraints with a permit-gated deviation in their `condition` (see
    :func:`_is_permit_gated_deviation`) are skipped: they describe a
    higher max attainable only with extra approval, not the base height.
    Stipulations on the same value (e.g. "geldt als gemiddelde") are
    kept; the value itself is the base max.

    Returns the updated Geometry plus a list of ReconciliationFinding
    records. The Geometry is a new instance; the input is not mutated.
    """
    geo_dump = geometry.model_dump()
    new_geometry = Geometry.model_validate(geo_dump)
    bouwvlakken = new_geometry.bouwvlakken

    poly_labels: list[set[str]] = [_polygon_labels(p) for p in bouwvlakken]

    all_height_max = [
        c
        for c in framework.constraints.numerical
        if c.category == "height"
        and c.is_maximum is True
        and c.applies_to
        and isinstance(c.value, (int, float))
    ]
    height_constraints = [c for c in all_height_max if is_base_height_constraint(c)]
    skipped_non_base_ids = sorted(
        c.id for c in all_height_max if not is_base_height_constraint(c)
    )

    findings: list[ReconciliationFinding] = []
    # winners[(poly_idx, label)] = chosen constraint
    winners: dict[tuple[int, str], NumericalConstraint] = {}
    # unmatched_winners[label] = chosen constraint when no polygon matched
    unmatched_winners: dict[str, NumericalConstraint] = {}

    for label_raw in {a for c in height_constraints for a in c.applies_to}:
        label = _normalise_label(label_raw)

        candidates = [
            c
            for c in height_constraints
            if any(_normalise_label(a) == label for a in c.applies_to)
            and not _is_permit_gated_deviation(c.condition)
        ]
        if not candidates:
            continue

        winner = _pick_winner(candidates)

        matched_poly_indices = [
            i for i, lbls in enumerate(poly_labels) if label in lbls
        ]

        if not matched_poly_indices:
            existing = unmatched_winners.get(label)
            if existing is None or (
                winner.confidence.score,
                winner.condition is None,
            ) > (existing.confidence.score, existing.condition is None):
                unmatched_winners[label] = winner
            continue

        for idx in matched_poly_indices:
            key = (idx, label)
            existing = winners.get(key)
            if existing is None or (
                winner.confidence.score,
                winner.condition is None,
            ) > (existing.confidence.score, existing.condition is None):
                winners[key] = winner

    reconciled_indices: set[int] = set()
    for (idx, label), constraint in winners.items():
        new_height = float(constraint.value)  # type: ignore[arg-type]
        previous = bouwvlakken[idx].height_m
        reconciled_indices.add(idx)

        if previous is None:
            action: ReconciliationAction = "inferred"
            bouwvlakken[idx].height_m = new_height
            bouwvlakken[idx].height_reconciled_from = "regels"
        elif abs(previous - new_height) <= HEIGHT_MATCH_TOLERANCE_M:
            action = "matched"
            bouwvlakken[idx].height_reconciled_from = "verbeelding"
        else:
            action = "corrected"
            bouwvlakken[idx].height_m = new_height
            bouwvlakken[idx].height_reconciled_from = "regels"

        findings.append(
            ReconciliationFinding(
                polygon_index=idx,
                label=label,
                action=action,
                previous_height_m=previous,
                new_height_m=new_height,
                source_constraint_id=constraint.id,
                source_constraint_provenance=constraint.provenance,
            )
        )

    for i, p in enumerate(bouwvlakken):
        if i not in reconciled_indices and p.height_reconciled_from is None:
            p.height_reconciled_from = "verbeelding_uncorrected"

    for label, constraint in unmatched_winners.items():
        findings.append(
            ReconciliationFinding(
                polygon_index=-1,
                label=label,
                action="unmatched",
                previous_height_m=None,
                new_height_m=float(constraint.value),  # type: ignore[arg-type]
                source_constraint_id=constraint.id,
                source_constraint_provenance=constraint.provenance,
            )
        )

    if skipped_non_base_ids:
        findings.append(
            ReconciliationFinding(
                polygon_index=-1,
                label="",
                action="skipped_non_base",
                previous_height_m=None,
                new_height_m=0.0,
                source_constraint_id="",
                source_constraint_provenance=Provenance(
                    source_type="inferred",  # type: ignore[arg-type]
                    inferred_from=skipped_non_base_ids,
                ),
                non_base_height_constraints_skipped=skipped_non_base_ids,
            )
        )
        logger.info(
            "Skipped {} non-base height constraints during reconciliation: {}",
            len(skipped_non_base_ids),
            skipped_non_base_ids,
        )

    counts = {
        a: 0
        for a in (
            "inferred",
            "matched",
            "corrected",
            "unmatched",
            "skipped_non_base",
        )
    }
    for f in findings:
        counts[f.action] += 1
    logger.info(
        "Height reconciliation: {} inferred, {} matched, {} corrected, "
        "{} unmatched (out of {} bouwvlakken, {} height constraints)",
        counts["inferred"],
        counts["matched"],
        counts["corrected"],
        counts["unmatched"],
        len(bouwvlakken),
        len(height_constraints),
    )

    return new_geometry, findings
