"""Tests for the Stage 4b IMRO cross-validation layer.

All IMRO API calls are mocked with respx; no live calls. Tests assert
graceful degradation, agreement/disagreement flagging, and shape — never
specific real-world values.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from omrt_extractor import cross_validate as cv_mod
from omrt_extractor.cross_validate import (
    API_IMRO,
    IMRO_API_BASE,
    cross_validate_imro,
)
from omrt_extractor.schemas import (
    Confidence,
    Constraints,
    KPIs,
    NumericalConstraint,
    Objective,
    ParametricFramework,
    ProgrammeProposal,
    ProjectLocation,
    ProjectMetadata,
    Provenance,
    SourceDocument,
    SourceType,
    UseSplit,
    Variables,
)

PLAN_ID = "NL.IMRO.0363.N2102BPGST-VG01"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cv_mod.settings, "project_root", tmp_path, raising=False)


def _provenance() -> Provenance:
    return Provenance(
        source_type=SourceType.DOCUMENT,
        document="regels.pdf",
        page=12,
        quoted_text="bouwhoogte ten hoogste 21 meter",
    )


def _confidence(score: float = 0.95) -> Confidence:
    return Confidence(score=score, reasons=["clear regels clause"])


def _height_constraint(value: float, cid: str = "max_height_a") -> NumericalConstraint:
    return NumericalConstraint(
        id=cid,
        name="Max building height A",
        category="height",
        value=value,
        unit="m",
        is_maximum=True,
        provenance=_provenance(),
        confidence=_confidence(),
    )


def _framework(
    constraints: list[NumericalConstraint], plan_id: str | None = PLAN_ID
) -> ParametricFramework:
    prov = _provenance()
    conf = _confidence()
    return ParametricFramework(
        metadata=ProjectMetadata(
            project_name="Test project",
            location=ProjectLocation(
                municipality="Amsterdam",
                centroid_rd=(121000.0, 489000.0),
                plan_id=plan_id,
            ),
            source_documents=[
                SourceDocument(
                    filename="regels.pdf",
                    document_type="regels",
                    page_count=20,
                    sha256="a" * 64,
                )
            ],
            tool_version="0.1.0",
        ),
        objective=Objective(
            statement="Mixed use",
            urban_intent="Active plinth, residential above",
            provenance=prov,
            confidence=conf,
        ),
        constraints=Constraints(numerical=constraints),
        variables=Variables(),
        kpis=KPIs(),
        programme=ProgrammeProposal(
            target_total_gfa_m2=10000,
            use_split=UseSplit(
                residential_m2=8000,
                productive_m2=1000,
                office_m2=0,
                retail_horeca_m2=500,
                cultural_m2=0,
                social_m2=500,
                other_m2=0,
                rationale="From toelichting",
                provenance=prov,
                confidence=conf,
            ),
            unit_mix=[],
            reasoning_trace=["From toelichting"],
            provenance=prov,
            confidence=conf,
        ),
    )


def _imro_plan_payload() -> dict:
    return {"id": PLAN_ID, "naam": "Test plan"}


def _imro_bestemmingsvlakken_payload() -> dict:
    return {"features": []}


def _imro_maatvoeringen_payload(height_value: float = 21.0) -> dict:
    return {
        "features": [
            {
                "properties": {
                    "naam": "maximum bouwhoogte",
                    "waarde": height_value,
                    "eenheid": "m",
                    "bestemmingsvlakId": "vlak_a",
                }
            }
        ]
    }


def _mock_imro_endpoints(height_value: float = 21.0) -> None:
    base = f"{IMRO_API_BASE}/plannen/{PLAN_ID}"
    respx.get(base).mock(return_value=httpx.Response(200, json=_imro_plan_payload()))
    respx.get(f"{base}/bestemmingsvlakken").mock(
        return_value=httpx.Response(200, json=_imro_bestemmingsvlakken_payload())
    )
    respx.get(f"{base}/maatvoeringen").mock(
        return_value=httpx.Response(200, json=_imro_maatvoeringen_payload(height_value))
    )


@respx.mock
def test_agreement_flags_constraint_within_tolerance() -> None:
    _mock_imro_endpoints(height_value=21.0)
    framework = _framework([_height_constraint(20.5)])

    result = cross_validate_imro(framework)

    [c] = result.constraints.numerical
    assert c.cross_validation is not None
    assert c.cross_validation.agreement == "agreement"
    assert c.cross_validation.source == API_IMRO
    assert c.cross_validation.authoritative_value == 21.0
    assert "imro_api_agreement" in c.confidence.flags
    # Score unchanged on agreement.
    assert c.confidence.score == 0.95


@respx.mock
def test_disagreement_lowers_confidence_and_flags() -> None:
    _mock_imro_endpoints(height_value=21.0)
    # Extracted 31 vs authoritative 21: a Scenario-1-style corruption.
    framework = _framework([_height_constraint(31.0)])

    result = cross_validate_imro(framework)

    [c] = result.constraints.numerical
    assert c.cross_validation is not None
    assert c.cross_validation.agreement == "disagreement"
    assert c.cross_validation.authoritative_value == 21.0
    assert "imro_api_disagreement" in c.confidence.flags
    # Score reduced by 0.3, clipped to >= 0.
    assert c.confidence.score == pytest.approx(0.65)


@respx.mock
def test_no_authoritative_match_marks_unverifiable() -> None:
    _mock_imro_endpoints(height_value=21.0)
    # Parking norm has no authoritative equivalent in the mocked payload.
    parking = NumericalConstraint(
        id="parking_norm",
        name="Parking norm",
        category="parking",
        value=0.5,
        unit="per_dwelling",
        is_maximum=False,
        provenance=_provenance(),
        confidence=_confidence(),
    )
    framework = _framework([parking])

    result = cross_validate_imro(framework)

    [c] = result.constraints.numerical
    assert c.cross_validation is not None
    assert c.cross_validation.agreement == "unverifiable"
    assert "imro_api_disagreement" not in c.confidence.flags
    assert "imro_api_agreement" not in c.confidence.flags


def test_no_plan_id_marks_every_constraint_not_attempted() -> None:
    framework = _framework(
        [_height_constraint(21.0, "a"), _height_constraint(15.0, "b")],
        plan_id=None,
    )

    result = cross_validate_imro(framework)

    for c in result.constraints.numerical:
        assert c.cross_validation is not None
        assert c.cross_validation.agreement == "not_attempted"
        assert c.cross_validation.source == API_IMRO
        assert "No IMRO plan ID" in (c.cross_validation.notes or "")


def test_non_imro_plan_id_marks_not_attempted() -> None:
    framework = _framework([_height_constraint(21.0)], plan_id="some-other-id")

    result = cross_validate_imro(framework)

    [c] = result.constraints.numerical
    assert c.cross_validation is not None
    assert c.cross_validation.agreement == "not_attempted"


@respx.mock
def test_api_503_falls_through_gracefully() -> None:
    base = f"{IMRO_API_BASE}/plannen/{PLAN_ID}"
    respx.get(base).mock(return_value=httpx.Response(503))
    respx.get(f"{base}/bestemmingsvlakken").mock(return_value=httpx.Response(503))
    respx.get(f"{base}/maatvoeringen").mock(return_value=httpx.Response(503))

    framework = _framework([_height_constraint(21.0)])
    result = cross_validate_imro(framework)

    [c] = result.constraints.numerical
    assert c.cross_validation is not None
    assert c.cross_validation.agreement == "not_attempted"
    assert "503" in (c.cross_validation.notes or "") or "unreachable" in (
        c.cross_validation.notes or ""
    )


@respx.mock
def test_network_error_falls_through_gracefully() -> None:
    base = f"{IMRO_API_BASE}/plannen/{PLAN_ID}"
    respx.get(base).mock(side_effect=httpx.ConnectError("boom"))

    framework = _framework([_height_constraint(21.0)])
    result = cross_validate_imro(framework)

    [c] = result.constraints.numerical
    assert c.cross_validation is not None
    assert c.cross_validation.agreement == "not_attempted"


@respx.mock
def test_original_framework_not_mutated() -> None:
    _mock_imro_endpoints(height_value=21.0)
    framework = _framework([_height_constraint(31.0)])

    result = cross_validate_imro(framework)

    # The returned object is a new framework; the input's confidence and
    # cross_validation are unchanged.
    assert framework.constraints.numerical[0].cross_validation is None
    assert framework.constraints.numerical[0].confidence.score == 0.95
    assert result is not framework
