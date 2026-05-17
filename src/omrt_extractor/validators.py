"""Universal sanity bounds for extracted constraint values.

Layer 5 of the Scenario 1 defence stack. Operates on a populated
ParametricFramework. Returns a list of ValidationFinding objects
describing values that fall outside universal physical-sense bounds
or programme self-consistency. Does not modify the framework; the
viewer and the summary surface findings.

Bounds are universal (apply to any Dutch project, indeed any project),
not municipality-specific. They catch the rare LLM hallucination that
escapes the IMRO API cross-validation — when a project has no published
plan ID, when the hallucinated value happens to coincide with what the
matcher misclassified, or when an API call failed.

Primary entry point:
    run_all_validations(framework) -> list[ValidationFinding]
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from omrt_extractor.schemas import NumericalConstraint, ParametricFramework

# ---------------------------------------------------------------------
# Universal physical-sense bounds (heights, ratios, areas)
# ---------------------------------------------------------------------

# Bounds chosen to be truly universal: a value outside is physically
# implausible for ANY construction project, not just Dutch ones. The
# point is to catch order-of-magnitude errors, not to flag unusual but
# valid values. Unusualness is the Confidence layer's job.
HEIGHT_BOUNDS_M = (0.5, 250.0)            # fences ≥0.5 m, no building tops Burj at 250 m
SETBACK_BOUNDS_M = (0.0, 500.0)           # 500 m setback only on extreme zoning
PARKING_PER_DWELLING_BOUNDS = (0.0, 5.0)  # >5 cars per home is implausible
FSI_FAR_BOUNDS = (0.0, 10.0)              # FSI >10 is Hong Kong tower territory
BVO_LIMIT_BOUNDS_M2 = (1.0, 5_000_000.0)  # rules can bind tiny utility blocks; 5M m² caps projects

CATEGORY_BOUNDS: dict[str, tuple[float, float]] = {
    "height": HEIGHT_BOUNDS_M,
    "setback": SETBACK_BOUNDS_M,
    "parking": PARKING_PER_DWELLING_BOUNDS,
    "fsi_far": FSI_FAR_BOUNDS,
    "bvo_limit": BVO_LIMIT_BOUNDS_M2,
}

# Parking constraints span heterogeneous units (per_dwelling, percent,
# parking_spaces, parking_spaces_per_dwelling). The per-dwelling bound
# only applies to the first; other units are skipped.
_PARKING_BOUND_UNITS = {"per_dwelling", "per_100m2_bvo"}

# Programme consistency tolerances
_USE_SPLIT_TOLERANCE = 0.01  # ±1% of target_total_gfa_m2
_UNIT_MIX_TOLERANCE = 0.05   # ±0.05 around sum=1.0
_DWELLING_SIZE_AVG_M2 = 80.0  # rough avg used only as a sanity cross-check
_DWELLING_SIZE_TOLERANCE = 0.5  # ±50% — generous; this is a sanity check, not a spec


Severity = Literal["warning", "error"]


class ValidationFinding(BaseModel):
    """A single sanity or programme-consistency finding.

    `kind` distinguishes physical-sense bound checks from programme
    self-consistency checks so the viewer can group them.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["sanity_bound", "programme_consistency"]
    constraint_id: str | None = Field(
        default=None,
        description="ID of the offending NumericalConstraint, when applicable.",
    )
    constraint_name: str | None = None
    value: float
    unit: str
    category: str
    bound: tuple[float, float]
    severity: Severity
    message: str
    provenance_document: str | None = None
    provenance_page: int | None = None


# ---------------------------------------------------------------------
# Sanity bound checks
# ---------------------------------------------------------------------


def _check_value(
    constraint: NumericalConstraint, numeric: float, bound: tuple[float, float]
) -> ValidationFinding | None:
    """Return an error finding if `numeric` is outside `bound`, else None.

    Layer 5 only emits hard errors — proximity warnings are the Confidence
    layer's job and generate noise on real data without adding signal.
    """
    lo, hi = bound
    if numeric < lo or numeric > hi:
        msg = (
            f"{constraint.name} = {numeric} {constraint.unit} is outside the "
            f"universal {constraint.category} bound {bound}."
        )
        return _make_finding(
            constraint=constraint,
            value=numeric,
            bound=bound,
            severity="error",
            message=msg,
        )
    return None


def _make_finding(
    *,
    constraint: NumericalConstraint,
    value: float,
    bound: tuple[float, float],
    severity: Severity,
    message: str,
) -> ValidationFinding:
    return ValidationFinding(
        kind="sanity_bound",
        constraint_id=constraint.id,
        constraint_name=constraint.name,
        value=float(value),
        unit=constraint.unit,
        category=constraint.category,
        bound=bound,
        severity=severity,
        message=message,
        provenance_document=constraint.provenance.document,
        provenance_page=constraint.provenance.page,
    )


def check_sanity_bounds(framework: ParametricFramework) -> list[ValidationFinding]:
    """Check every numerical constraint against universal physical-sense bounds.

    Categories without a universal physical bound (use_mix, sustainability,
    noise, accessibility, other) are skipped silently. Range values
    (tuple) are checked at both endpoints.
    """
    findings: list[ValidationFinding] = []
    for c in framework.constraints.numerical:
        bound = CATEGORY_BOUNDS.get(c.category)
        if bound is None:
            continue
        if c.category == "parking" and c.unit not in _PARKING_BOUND_UNITS:
            # parking covers heterogeneous units (percent EV, bicycle space
            # counts, scooter spaces). The per-dwelling bound only fits
            # per_dwelling / per_100m2_bvo norms.
            continue
        if isinstance(c.value, tuple):
            values = [float(v) for v in c.value]
        else:
            values = [float(c.value)]
        for v in values:
            finding = _check_value(c, v, bound)
            if finding is not None:
                findings.append(finding)
    return findings


# ---------------------------------------------------------------------
# Programme consistency checks
# ---------------------------------------------------------------------


def _programme_finding(
    *,
    category: str,
    value: float,
    bound: tuple[float, float],
    severity: Severity,
    message: str,
) -> ValidationFinding:
    return ValidationFinding(
        kind="programme_consistency",
        constraint_id=None,
        constraint_name=category,
        value=float(value),
        unit="ratio" if category != "use_split_gfa" else "m2",
        category=category,
        bound=bound,
        severity=severity,
        message=message,
    )


def check_programme_sanity(framework: ParametricFramework) -> list[ValidationFinding]:
    """Programme self-consistency checks beyond raw bounds.

    - use_split components must sum to target_total_gfa_m2 (±1%)
    - unit_mix fraction_of_total_dwellings must sum to 1.0 (±0.05)
    - target_dwelling_count consistent with residential_m2 / 80 m² avg
      (very loose ±50% — only catches order-of-magnitude errors)
    """
    findings: list[ValidationFinding] = []
    prog = framework.programme

    use_split_sum = (
        prog.use_split.residential_m2
        + prog.use_split.productive_m2
        + prog.use_split.office_m2
        + prog.use_split.retail_horeca_m2
        + prog.use_split.cultural_m2
        + prog.use_split.social_m2
        + prog.use_split.other_m2
    )
    target = prog.target_total_gfa_m2
    if target > 0:
        rel_err = abs(use_split_sum - target) / target
        bound = (target * (1 - _USE_SPLIT_TOLERANCE), target * (1 + _USE_SPLIT_TOLERANCE))
        if rel_err > _USE_SPLIT_TOLERANCE:
            findings.append(
                _programme_finding(
                    category="use_split_gfa",
                    value=use_split_sum,
                    bound=bound,
                    severity="error",
                    message=(
                        f"use_split components sum to {use_split_sum:.0f} m² but "
                        f"target_total_gfa_m2 is {target:.0f} m² "
                        f"({rel_err * 100:.1f}% off; tolerance ±1%)."
                    ),
                )
            )

    if prog.unit_mix:
        frac_sum = sum(u.fraction_of_total_dwellings for u in prog.unit_mix)
        bound = (1.0 - _UNIT_MIX_TOLERANCE, 1.0 + _UNIT_MIX_TOLERANCE)
        if abs(frac_sum - 1.0) > _UNIT_MIX_TOLERANCE:
            findings.append(
                _programme_finding(
                    category="unit_mix_fraction",
                    value=frac_sum,
                    bound=bound,
                    severity="error" if abs(frac_sum - 1.0) > 0.15 else "warning",
                    message=(
                        f"unit_mix fractions sum to {frac_sum:.3f}; expected 1.0 ± "
                        f"{_UNIT_MIX_TOLERANCE}."
                    ),
                )
            )

    if prog.target_dwelling_count and prog.use_split.residential_m2 > 0:
        implied = prog.use_split.residential_m2 / _DWELLING_SIZE_AVG_M2
        if implied > 0:
            ratio = prog.target_dwelling_count / implied
            if abs(ratio - 1.0) > _DWELLING_SIZE_TOLERANCE:
                findings.append(
                    _programme_finding(
                        category="dwelling_count_vs_residential_m2",
                        value=float(prog.target_dwelling_count),
                        bound=(
                            implied * (1 - _DWELLING_SIZE_TOLERANCE),
                            implied * (1 + _DWELLING_SIZE_TOLERANCE),
                        ),
                        severity="warning",
                        message=(
                            f"target_dwelling_count={prog.target_dwelling_count} implies "
                            f"avg dwelling size {prog.use_split.residential_m2 / prog.target_dwelling_count:.0f} m² "
                            f"(rough sanity reference: {_DWELLING_SIZE_AVG_M2:.0f} m² avg, "
                            f"±{int(_DWELLING_SIZE_TOLERANCE * 100)}% tolerance)."
                        ),
                    )
                )

    return findings


# ---------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------


_SEVERITY_RANK = {"error": 0, "warning": 1}


def run_all_validations(framework: ParametricFramework) -> list[ValidationFinding]:
    """Run sanity bounds and programme consistency checks.

    Returns findings sorted by severity (errors first) then category.
    Does not modify the framework. Findings are advisory; the PM decides
    whether to act on each.
    """
    findings = check_sanity_bounds(framework) + check_programme_sanity(framework)
    findings.sort(key=lambda f: (_SEVERITY_RANK[f.severity], f.category, f.constraint_id or ""))
    return findings
