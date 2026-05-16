"""IMRO API cross-validation: Scenario 1 defence, Layer 4b.

For Dutch projects with a published plan_id matching the IMRO pattern,
queries the Ruimtelijke Plannen API v4 and compares every extracted
NumericalConstraint against the authoritative value within the
configured relative tolerance (default 5%).

Primary function:
    cross_validate_imro(framework) -> ParametricFramework

Returns a new framework with cross_validation populated on every
NumericalConstraint that has an authoritative equivalent. Confidence
flags are also updated: 'imro_api_agreement' on match,
'imro_api_disagreement' on mismatch (with score reduced by 0.3,
clipped to 0).

API endpoint:
    https://ruimte.omgevingswet.overheid.nl/ruimtelijke-plannen/api/opvragen/v4/

Graceful degradation:
- No plan_id           -> every constraint gets agreement='not_attempted'
- API unreachable      -> every constraint gets agreement='not_attempted' with network error note
- Field cannot match   -> agreement='unverifiable' with brief note
- Match within tol     -> agreement='agreement'
- Match outside tol    -> agreement='disagreement', viewer surfaces both

Stage 4b of the build plan.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel

from .config import settings
from .schemas import (
    ConstraintCategory,
    CrossValidation,
    NumericalConstraint,
    ParametricFramework,
)

API_IMRO = "imro_plannen_v4"
IMRO_API_BASE = "https://ruimte.omgevingswet.overheid.nl/ruimtelijke-plannen/api/opvragen/v4"
IMRO_PLAN_ID_PATTERN = re.compile(r"^NL\.IMRO\.[a-zA-Z0-9.-]+$")

# Naam-substring → ConstraintCategory. Lowercase, longest first so e.g.
# 'bebouwingspercentage' wins over a generic 'bebouwing' match.
_NAAM_TO_CATEGORY: list[tuple[str, ConstraintCategory]] = [
    ("bebouwingspercentage", "footprint"),
    ("bouwhoogte", "height"),
    ("goothoogte", "height"),
    ("nokhoogte", "height"),
    ("hoogte", "height"),
    ("bruto-vloeroppervlak", "bvo_limit"),
    ("vloeroppervlak", "bvo_limit"),
    ("bvo", "bvo_limit"),
    ("bvo_limit", "bvo_limit"),
    ("parkeernorm", "parking"),
    ("parkeren", "parking"),
    ("fsi", "fsi_far"),
    ("far", "fsi_far"),
    ("vloerindex", "fsi_far"),
    ("setback", "setback"),
    ("terugligging", "setback"),
]


@dataclass
class _AuthoritativeValue:
    """An authoritative numerical value pulled from the IMRO API.

    `applies_to_codes` carries any bestemmingsvlak identifiers (gml_id,
    bestemming code, aanduiding) that the authoritative record binds to.
    The matcher uses this to disambiguate when multiple values share a
    category.
    """

    category: ConstraintCategory
    value: float | tuple[float, float]
    unit: str | None
    applies_to_codes: list[str] = field(default_factory=list)
    raw_naam: str | None = None


# ---------------------------------------------------------------------
# API I/O
# ---------------------------------------------------------------------


def _cache_path_for(plan_id: str) -> Path:
    d = settings.cache_dir / "imro"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{plan_id}.json"


def _read_cache(plan_id: str) -> dict[str, Any] | None:
    path = _cache_path_for(plan_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(plan_id: str, payload: dict[str, Any]) -> None:
    try:
        _cache_path_for(plan_id).write_text(json.dumps(payload))
    except (OSError, TypeError) as exc:
        logger.warning(f"Failed to write IMRO cache: {exc}")


def _fetch_imro(
    plan_id: str, client: httpx.Client
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch the plan, its bestemmingsvlakken and maatvoeringen.

    Returns (payload, error_note). On any network or non-200 condition
    payload is None and error_note holds a short human-readable reason.
    """
    cached = _read_cache(plan_id)
    if cached is not None:
        return cached, None

    base = f"{IMRO_API_BASE}/plannen/{plan_id}"
    endpoints = {
        "plan": base,
        "bestemmingsvlakken": f"{base}/bestemmingsvlakken",
        "maatvoeringen": f"{base}/maatvoeringen",
    }

    combined: dict[str, Any] = {}
    for key, url in endpoints.items():
        try:
            r = client.get(url, timeout=30.0)
        except httpx.HTTPError as exc:
            note = f"IMRO API network error on {key}: {exc}"
            logger.warning(note)
            return None, note
        if r.status_code != 200:
            note = f"IMRO API returned HTTP {r.status_code} on {key}"
            logger.warning(note)
            return None, note
        try:
            combined[key] = r.json()
        except ValueError:
            note = f"IMRO API returned non-JSON on {key}"
            logger.warning(note)
            return None, note

    _write_cache(plan_id, combined)
    return combined, None


# ---------------------------------------------------------------------
# Parsing the IMRO response into authoritative values
# ---------------------------------------------------------------------


def _features_of(payload_section: Any) -> list[dict[str, Any]]:
    """Tolerate a few common payload shapes (FeatureCollection, HAL, raw list)."""
    if isinstance(payload_section, list):
        return [x for x in payload_section if isinstance(x, dict)]
    if isinstance(payload_section, dict):
        if isinstance(payload_section.get("features"), list):
            return [x for x in payload_section["features"] if isinstance(x, dict)]
        if isinstance(payload_section.get("_embedded"), dict):
            for v in payload_section["_embedded"].values():
                if isinstance(v, list):
                    return [x for x in v if isinstance(x, dict)]
        if isinstance(payload_section.get("_links"), dict) and "items" in payload_section:
            items = payload_section.get("items")
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)]
    return []


def _props(feature: dict[str, Any]) -> dict[str, Any]:
    p = feature.get("properties")
    return p if isinstance(p, dict) else feature


def _classify_naam(naam: str) -> ConstraintCategory | None:
    low = naam.lower()
    for substr, category in _NAAM_TO_CATEGORY:
        if substr in low:
            return category
    return None


def _coerce_value(raw: Any) -> float | tuple[float, float] | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw.replace(",", ".").strip())
        except ValueError:
            return None
    if isinstance(raw, list | tuple) and len(raw) == 2:
        lo = _coerce_value(raw[0])
        hi = _coerce_value(raw[1])
        if isinstance(lo, float) and isinstance(hi, float):
            return (lo, hi)
    return None


def _codes_from_props(props: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for key in (
        "bestemmingsvlakId",
        "bestemmingsvlak_id",
        "bestemmingscode",
        "aanduiding",
        "gml_id",
        "identificatie",
    ):
        v = props.get(key)
        if isinstance(v, str) and v:
            codes.append(v)
        elif isinstance(v, list):
            codes.extend(str(x) for x in v if isinstance(x, str))
    return codes


def _parse_authoritative(payload: dict[str, Any]) -> list[_AuthoritativeValue]:
    """Walk the combined IMRO payload, return a flat list of authoritative values."""
    out: list[_AuthoritativeValue] = []

    for feat in _features_of(payload.get("maatvoeringen")):
        props = _props(feat)
        naam = props.get("naam") or props.get("type") or props.get("kenmerk")
        if not isinstance(naam, str):
            continue
        category = _classify_naam(naam)
        if category is None:
            continue
        raw_val = props.get("waarde")
        if raw_val is None:
            raw_val = props.get("value")
        value = _coerce_value(raw_val)
        if value is None:
            continue
        unit = props.get("eenheid") if isinstance(props.get("eenheid"), str) else None
        out.append(
            _AuthoritativeValue(
                category=category,
                value=value,
                unit=unit,
                applies_to_codes=_codes_from_props(props),
                raw_naam=naam,
            )
        )

    # Bestemmingsvlakken occasionally embed inline maatvoeringen.
    for feat in _features_of(payload.get("bestemmingsvlakken")):
        props = _props(feat)
        codes = _codes_from_props(props)
        inline = props.get("maatvoeringen")
        if not isinstance(inline, list):
            continue
        for m in inline:
            if not isinstance(m, dict):
                continue
            naam = m.get("naam") or m.get("type")
            if not isinstance(naam, str):
                continue
            category = _classify_naam(naam)
            if category is None:
                continue
            value = _coerce_value(m.get("waarde", m.get("value")))
            if value is None:
                continue
            unit = m.get("eenheid") if isinstance(m.get("eenheid"), str) else None
            out.append(
                _AuthoritativeValue(
                    category=category,
                    value=value,
                    unit=unit,
                    applies_to_codes=codes,
                    raw_naam=naam,
                )
            )

    return out


# ---------------------------------------------------------------------
# Matching and comparison
# ---------------------------------------------------------------------


def _scalar(value: float | tuple[float, float], is_maximum: bool | None) -> float:
    """Reduce a value to a single number for comparison.

    Tuple values use is_maximum to choose a bound; default to the upper
    bound when unspecified (heights and BVO limits are almost always
    maxima in Dutch planning).
    """
    if isinstance(value, tuple):
        return value[1] if (is_maximum is None or is_maximum) else value[0]
    return float(value)


def _within_tolerance(a: float, b: float, tol: float) -> bool:
    denom = max(abs(a), abs(b))
    if denom == 0.0:
        return a == b
    return abs(a - b) / denom <= tol


def _match(
    constraint: NumericalConstraint, candidates: list[_AuthoritativeValue]
) -> _AuthoritativeValue | None:
    """Pick the best authoritative candidate for a constraint.

    Strategy:
      1. Filter to candidates with the same category.
      2. Prefer candidates whose applies_to_codes overlap the constraint's
         applies_to list.
      3. Otherwise fall back to the first same-category candidate.
    """
    same_category = [c for c in candidates if c.category == constraint.category]
    if not same_category:
        return None

    if constraint.applies_to:
        applies = set(constraint.applies_to)
        with_overlap = [c for c in same_category if applies.intersection(c.applies_to_codes)]
        if with_overlap:
            return with_overlap[0]

    return same_category[0]


# ---------------------------------------------------------------------
# Building updated constraints
# ---------------------------------------------------------------------


def _with_cross_validation(
    constraint: NumericalConstraint,
    cross_validation: CrossValidation,
    extra_flag: str | None,
    score_delta: float,
) -> NumericalConstraint:
    """Return a new NumericalConstraint with updated cross_validation and confidence.

    Uses model_validate(model_dump() | ...) per CLAUDE.md so nested
    validators re-fire on the new instance.
    """
    confidence = constraint.confidence
    flags = list(confidence.flags)
    if extra_flag and extra_flag not in flags:
        flags.append(extra_flag)
    new_score = max(0.0, min(1.0, confidence.score + score_delta))

    base = constraint.model_dump()
    base["confidence"] = {
        **base["confidence"],
        "flags": flags,
        "score": new_score,
    }
    base["cross_validation"] = cross_validation.model_dump()
    return NumericalConstraint.model_validate(base)


def _not_attempted_constraint(constraint: NumericalConstraint, note: str) -> NumericalConstraint:
    cv = CrossValidation(source=API_IMRO, agreement="not_attempted", notes=note)
    return _with_cross_validation(constraint, cv, extra_flag=None, score_delta=0.0)


# ---------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------


def cross_validate_imro(
    framework: ParametricFramework,
    client: httpx.Client | None = None,
    tolerance: float = settings.imro_cross_validation_tolerance,
) -> ParametricFramework:
    """Cross-validate every NumericalConstraint against the IMRO API.

    Returns a new ParametricFramework with `cross_validation` and
    `confidence.flags` updated on each numerical constraint. The original
    framework is not mutated.

    See module docstring for the graceful-degradation matrix.
    """
    plan_id = framework.metadata.location.plan_id
    constraints = framework.constraints.numerical

    # Graceful path 1: no plan_id or non-IMRO id.
    if not plan_id or not IMRO_PLAN_ID_PATTERN.match(plan_id):
        logger.info("No IMRO plan ID on project; skipping IMRO cross-validation")
        updated = [
            _not_attempted_constraint(c, "No IMRO plan ID on this project") for c in constraints
        ]
        return _replace_numerical(framework, updated)

    # Fetch authoritative payload.
    owned_client = client is None
    http = client or httpx.Client()
    try:
        payload, err = _fetch_imro(plan_id, http)
    finally:
        if owned_client:
            http.close()

    # Graceful path 2: API unreachable.
    if payload is None:
        note = f"IMRO API unreachable: {err}" if err else "IMRO API unreachable"
        updated = [_not_attempted_constraint(c, note) for c in constraints]
        return _replace_numerical(framework, updated)

    candidates = _parse_authoritative(payload)
    logger.info(
        f"IMRO cross-validation: {len(candidates)} authoritative values "
        f"available for plan {plan_id}"
    )

    updated: list[NumericalConstraint] = []
    for c in constraints:
        match = _match(c, candidates)
        if match is None:
            cv = CrossValidation(
                source=API_IMRO,
                agreement="unverifiable",
                tolerance_used=tolerance,
                notes=f"No authoritative value found for category '{c.category}'",
            )
            updated.append(_with_cross_validation(c, cv, extra_flag=None, score_delta=0.0))
            continue

        extracted_scalar = _scalar(c.value, c.is_maximum)
        auth_scalar = _scalar(match.value, c.is_maximum)
        agrees = _within_tolerance(extracted_scalar, auth_scalar, tolerance)

        cv = CrossValidation(
            source=API_IMRO,
            authoritative_value=match.value,
            authoritative_unit=match.unit,
            agreement="agreement" if agrees else "disagreement",
            tolerance_used=tolerance,
            notes=f"Matched on IMRO maatvoering '{match.raw_naam}'" if match.raw_naam else None,
        )
        flag = "imro_api_agreement" if agrees else "imro_api_disagreement"
        delta = 0.0 if agrees else -0.3
        updated.append(_with_cross_validation(c, cv, extra_flag=flag, score_delta=delta))

    return _replace_numerical(framework, updated)


def _replace_numerical(
    framework: ParametricFramework, numerical: list[NumericalConstraint]
) -> ParametricFramework:
    """Return a new ParametricFramework with the numerical constraints swapped in."""
    if not isinstance(framework, BaseModel):  # defensive
        raise TypeError("framework must be a ParametricFramework")
    base = framework.model_dump()
    base["constraints"] = {**base["constraints"], "numerical": [c.model_dump() for c in numerical]}
    return ParametricFramework.model_validate(base)
