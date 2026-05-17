"""Tests for src/omrt_extractor/constraint_filters.py.

Structural-only fixtures. Verify that the base-vs-non-base classifier
recognises additive deviations and peripheral element heights universally,
without depending on any specific Dutch municipality vocabulary.
"""

from __future__ import annotations

from omrt_extractor.constraint_filters import is_base_height_constraint
from omrt_extractor.schemas import (
    Confidence,
    NumericalConstraint,
    Provenance,
    SourceType,
)


def _prov() -> Provenance:
    return Provenance(
        source_type=SourceType.DOCUMENT,
        document="regels.pdf",
        page=1,
        quoted_text="max bouwhoogte is X m",
    )


def _conf() -> Confidence:
    return Confidence(score=0.95)


def _c(
    id: str,
    name: str,
    *,
    category: str = "height",
    is_maximum: bool | None = True,
    condition: str | None = None,
    value: float = 21.0,
) -> NumericalConstraint:
    return NumericalConstraint(
        id=id,
        name=name,
        category=category,  # type: ignore[arg-type]
        value=value,
        unit="m",
        is_maximum=is_maximum,
        condition=condition,
        provenance=_prov(),
        confidence=_conf(),
    )


def test_max_height_sba1_is_base() -> None:
    assert is_base_height_constraint(_c("max_height_sba1", "Maximum bouwhoogte sba-1"))


def test_avg_height_sba1_is_base() -> None:
    assert is_base_height_constraint(
        _c("avg_height_sba1", "Gemiddelde bouwhoogte sba-1")
    )


def test_hamerblok_base_height_is_base() -> None:
    assert is_base_height_constraint(
        _c("max_hamerblok_base_height", "Maximale bouwhoogte hamerblok")
    )


def test_deviation_rooftop_equipment_is_not_base() -> None:
    c = _c(
        "deviation_rooftop_equipment_height_increase",
        "Maximale overschrijding bouwhoogte voor schoorstenen, ventilatie etc. (afwijking)",
        condition="bij omgevingsvergunning ten behoeve van schoorstenen",
        value=5.0,
    )
    assert not is_base_height_constraint(c)


def test_reclamemasten_is_not_base() -> None:
    c = _c(
        "max_height_reclamemasten_verkeer",
        "Maximale bouwhoogte reclamemasten en vlaggenmasten",
        value=10.0,
    )
    assert not is_base_height_constraint(c)


def test_minimum_height_is_not_base() -> None:
    assert not is_base_height_constraint(
        _c("min_plint_height", "Minimum plint height", is_maximum=False, value=3.5)
    )


def test_additive_condition_rejected() -> None:
    c = _c(
        "max_height_extra_floor",
        "Extra hoogte boven hoofdmassa",
        condition="Maximale overschrijding van 4 m boven de maximale bouwhoogte",
        value=4.0,
    )
    assert not is_base_height_constraint(c)


def test_non_height_category_rejected() -> None:
    assert not is_base_height_constraint(
        _c("max_bvo", "Max BVO", category="bvo_limit", value=10000.0)
    )


def test_fence_is_not_base() -> None:
    assert not is_base_height_constraint(
        _c("max_height_fence_groen", "Erfafscheiding hoogte", value=2.0)
    )
