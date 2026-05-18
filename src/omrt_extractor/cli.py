"""Typer CLI: `omrt run <input_dir>` — the canonical pipeline entry point.

Derives a project name from the input directory basename and writes all
outputs to ``data/outputs/<project>/``. The four expensive stages
(extraction, programme inference, geo enrichment, IMRO cross-validation)
are skipped when their output file already exists, unless ``--force`` is
passed. The cheap chain (geometry parse, reconciliation, framework
assembly, handoff write, example massings) always runs so any change to
the assembly logic is reflected immediately.

Per-stage opt-outs (`--skip-extraction`, `--skip-programme`,
`--skip-enrich`, `--skip-cross-validate`) let the user re-run on a
partial cache without consuming API budget.

Commands:
    omrt run <input_dir>      Run the full pipeline
    omrt validate <path>      (placeholder)
    omrt archive <path>       (placeholder)

Stage 6 of the build plan.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import typer
from loguru import logger

app = typer.Typer(
    name="omrt",
    help="OMRT doc-extractor: Dutch project documents to Grasshopper framework.",
    no_args_is_help=True,
)


# =====================================================================
# Stage IO helpers
# =====================================================================


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def _find_pdf(input_dir: Path, hints: tuple[str, ...]) -> Path | None:
    for p in sorted(input_dir.iterdir()):
        if p.suffix.lower() != ".pdf":
            continue
        name = p.name.lower()
        if any(h in name for h in hints):
            return p
    return None


# =====================================================================
# Expensive stages (skip if cached)
# =====================================================================


def _run_extraction(input_dir: Path, cache_dir: Path, out_path: Path) -> dict[str, Any]:
    from omrt_extractor.extract import extract_project
    from omrt_extractor.preprocess import preprocess_project

    pre = preprocess_project(input_dir, cache_dir)
    result = asyncio.run(extract_project(pre))
    data = result.model_dump(mode="json")
    _write_json(out_path, data)
    return data


def _run_geo(framework, out_path: Path) -> dict[str, Any]:
    from omrt_extractor.enrich import enrich_3d_bag, enrich_geo

    geo = enrich_geo(framework.metadata.location)
    try:
        snap = enrich_3d_bag(framework.metadata.location)
        if snap.has_3d_bag_data:
            geo = geo.model_copy(update={"nearby_buildings": snap})
    except Exception as exc:  # noqa: BLE001
        logger.warning("3D BAG enrichment failed: {}", exc)
    data = geo.model_dump(mode="json")
    _write_json(out_path, data)
    return data


def _run_cross_validate(framework, out_path: Path) -> dict[str, Any]:
    from omrt_extractor.cross_validate import cross_validate_imro

    cv_framework = cross_validate_imro(framework)
    by_id: dict[str, Any] = {}
    for c in cv_framework.constraints.numerical:
        if c.cross_validation is not None:
            by_id[c.id] = {
                "cross_validation": c.cross_validation.model_dump(mode="json"),
                "confidence_flags": list(c.confidence.flags),
                "confidence_score": c.confidence.score,
            }
    _write_json(out_path, by_id)
    return by_id


def _run_programme(framework, geo_context, out_path: Path) -> dict[str, Any]:
    from omrt_extractor.infer import infer_programme

    proposal = infer_programme(framework, geo_context=geo_context)
    data = proposal.model_dump(mode="json")
    _write_json(out_path, data)
    return data


# =====================================================================
# Cheap stages (always run)
# =====================================================================


_SOURCE_DOC_TYPE_FROM_FILENAME = {
    "regels": "regels",
    "toelichting": "toelichting",
    "kaveltekening": "verbeelding",
    "verbeelding": "verbeelding",
    "plankaart": "verbeelding",
}


def _build_source_documents(input_dir: Path) -> list:
    """Scan the input dir for PDFs and build SourceDocument metadata.

    Computes SHA-256 of each PDF's bytes and reads page_count via pymupdf.
    Classification follows the same filename heuristic as preprocess.py;
    the LLM-decided document_type is not yet available at framework-
    assembly time.
    """
    import hashlib

    import pymupdf

    from omrt_extractor.schemas import SourceDocument

    docs: list = []
    for pdf_path in sorted(input_dir.iterdir()):
        if pdf_path.suffix.lower() != ".pdf":
            continue
        name_lc = pdf_path.name.lower()
        doc_type = "other"
        for hint, mapped in _SOURCE_DOC_TYPE_FROM_FILENAME.items():
            if hint in name_lc:
                doc_type = mapped
                break
        sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        with pymupdf.open(pdf_path) as pdf:
            page_count = pdf.page_count
        docs.append(
            SourceDocument(
                filename=pdf_path.name,
                document_type=doc_type,
                page_count=page_count,
                sha256=sha,
            )
        )
    return docs


def _dedup_by_id(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        out.append(item)
    return out


def _assemble_framework(
    project_name: str,
    extraction: dict,
    programme_data: dict,
    geo_data: dict | None,
    source_documents: list | None = None,
):
    """Build a ParametricFramework from cached stage outputs.

    Logic lifted from the legacy run_pipeline.py stitcher.
    """
    from omrt_extractor.schemas import (
        Confidence,
        Constraints,
        GeoContext,
        GeometricConstraint,
        KPIs,
        NarrativeConstraint,
        NumericalConstraint,
        Objective,
        ParametricFramework,
        ProgrammeProposal,
        ProjectLocation,
        ProjectMetadata,
        Provenance,
        SourceDocument,
        SourceType,
        Variables,
    )

    numerical = [
        NumericalConstraint.model_validate(c)
        for c in _dedup_by_id(extraction.get("numerical_constraints", []))
    ]
    narrative = [
        NarrativeConstraint.model_validate(c)
        for c in _dedup_by_id(extraction.get("narrative_constraints", []))
    ]
    geometric = [
        GeometricConstraint.model_validate(c)
        for c in _dedup_by_id(extraction.get("geometric_constraints", []))
    ]

    passages = extraction.get("urban_intent_passages", [])
    urban_intent = (
        " ".join(passages[:3]) if passages else "No urban intent passages extracted."
    )
    objective = Objective(
        statement=f"Inferred design goal for {project_name}.",
        urban_intent=urban_intent,
        provenance=Provenance(
            source_type=SourceType.INFERRED, inferred_from=["urban_intent_passages"]
        ),
        confidence=Confidence(score=0.5, reasons=["assembled from raw passages"]),
    )

    programme = ProgrammeProposal.model_validate(programme_data)

    municipalities = extraction.get("municipalities_found") or ["Amsterdam"]
    neighbourhoods = extraction.get("neighbourhoods_found") or []
    metadata = ProjectMetadata(
        project_name=project_name,
        location=ProjectLocation(
            municipality=municipalities[0],
            neighbourhood=neighbourhoods[0] if neighbourhoods else None,
            plan_id=(extraction.get("plan_ids_found") or [None])[0],
        ),
        source_documents=source_documents
        or [
            SourceDocument(
                filename="extraction_raw.json",
                document_type="other",
                page_count=1,
                sha256="0" * 64,
            )
        ],
        tool_version="0.1.0-omrt-run",
    )

    geo_context = GeoContext.model_validate(geo_data) if geo_data else None

    return ParametricFramework(
        metadata=metadata,
        objective=objective,
        constraints=Constraints(
            numerical=numerical, geometric=geometric, narrative=narrative
        ),
        variables=Variables(),
        kpis=KPIs(),
        programme=programme,
        geo_context=geo_context,
    )


def _apply_cross_validation(framework, cv_by_id: dict[str, Any]):
    """Re-attach cached cross_validation entries onto numerical constraints."""
    from omrt_extractor.schemas import CrossValidation, ParametricFramework

    if not cv_by_id:
        return framework
    payload = framework.model_dump(mode="json")
    for c in payload["constraints"]["numerical"]:
        entry = cv_by_id.get(c["id"])
        if entry is None:
            continue
        c["cross_validation"] = entry["cross_validation"]
        c["confidence"]["flags"] = entry["confidence_flags"]
        c["confidence"]["score"] = entry["confidence_score"]
        # round-trip-validate one field to ensure shape is correct
        CrossValidation.model_validate(entry["cross_validation"])
    return ParametricFramework.model_validate(payload)


# =====================================================================
# Orchestrator
# =====================================================================


@app.command()
def run(
    input_dir: str = typer.Argument(..., help="Project input directory (must contain PDFs)."),
    force: bool = typer.Option(False, "--force", help="Re-run all stages, ignoring caches."),
    skip_extraction: bool = typer.Option(False, "--skip-extraction"),
    skip_programme: bool = typer.Option(False, "--skip-programme"),
    skip_enrich: bool = typer.Option(False, "--skip-enrich"),
    skip_cross_validate: bool = typer.Option(False, "--skip-cross-validate"),
) -> None:
    """Run the pipeline on a project input directory."""
    from omrt_extractor.geometry import Geometry, merge_geometry_into_framework, parse_kaveltekening
    from omrt_extractor.massing import generate_example_massings
    from omrt_extractor.output import write_grasshopper_handoff
    from omrt_extractor.reconcile import reconcile_heights

    in_dir = Path(input_dir).resolve()
    if not in_dir.is_dir():
        typer.echo(f"Input directory not found: {in_dir}", err=True)
        raise typer.Exit(code=2)

    project = in_dir.name
    out_dir = Path("data/outputs") / project
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path("data/cache")

    paths = {
        "extraction": out_dir / "extraction_raw.json",
        "programme": out_dir / "programme.json",
        "geo": out_dir / "geo_context.json",
        "cross_validate": out_dir / "imro_cross_validation.json",
        "geometry": out_dir / "geometry.json",
        "reconciliation": out_dir / "reconciliation_report.json",
    }

    cached: list[str] = []
    fresh: list[str] = []

    source_documents = _build_source_documents(in_dir)

    # ---------- Stage: extraction ----------
    if skip_extraction or (paths["extraction"].exists() and not force):
        if not paths["extraction"].exists():
            typer.echo(
                f"--skip-extraction passed but {paths['extraction']} does not exist.",
                err=True,
            )
            raise typer.Exit(code=2)
        extraction = _load_json(paths["extraction"])
        cached.append("extraction")
    else:
        logger.info("Running extraction (expensive)…")
        extraction = _run_extraction(in_dir, cache_dir, paths["extraction"])
        fresh.append("extraction")

    # ---------- Stage: geo enrichment ----------
    # Requires a partial framework only for the location; assemble a minimal
    # stub from the extraction.
    if skip_enrich or (paths["geo"].exists() and not force):
        geo_data = _load_json(paths["geo"]) if paths["geo"].exists() else None
        if geo_data is not None:
            cached.append("geo")
    else:
        # Need a framework-with-location to call enrich_geo. Build a temporary
        # one with a stub programme just so the assembler succeeds; the real
        # framework gets assembled later with the real programme.
        from omrt_extractor.schemas import (
            Confidence,
            ProgrammeProposal,
            Provenance,
            SourceType,
            UnitTypeTarget,
            UseSplit,
        )

        stub_prov = Provenance(source_type=SourceType.INFERRED, inferred_from=["stub"])
        stub_conf = Confidence(score=0.1, reasons=["pre-enrichment stub"])
        stub_programme = ProgrammeProposal(
            target_total_gfa_m2=1.0,
            use_split=UseSplit(
                residential_m2=1.0,
                productive_m2=0.0,
                office_m2=0.0,
                retail_horeca_m2=0.0,
                cultural_m2=0.0,
                social_m2=0.0,
                other_m2=0.0,
                rationale="stub",
                provenance=stub_prov,
                confidence=stub_conf,
            ),
            unit_mix=[
                UnitTypeTarget(
                    tenure="sociale_huur",
                    size_band="mixed",
                    fraction_of_total_dwellings=1.0,
                    rationale="stub",
                    provenance=stub_prov,
                    confidence=stub_conf,
                )
            ],
            reasoning_trace=["stub"],
            provenance=stub_prov,
            confidence=stub_conf,
        )
        stub_framework = _assemble_framework(
            project,
            extraction,
            stub_programme.model_dump(mode="json"),
            None,
            source_documents=source_documents,
        )
        logger.info("Running geo enrichment (expensive)…")
        geo_data = _run_geo(stub_framework, paths["geo"])
        fresh.append("geo")

    # ---------- Stage: programme inference ----------
    if skip_programme or (paths["programme"].exists() and not force):
        if not paths["programme"].exists():
            typer.echo(
                f"--skip-programme passed but {paths['programme']} does not exist.",
                err=True,
            )
            raise typer.Exit(code=2)
        programme_data = _load_json(paths["programme"])
        cached.append("programme")
    else:
        from omrt_extractor.schemas import GeoContext

        # For inference we need a framework with constraints + geo. Stub
        # programme is fine here because infer_programme returns a fresh one.
        from omrt_extractor.schemas import (
            Confidence,
            ProgrammeProposal,
            Provenance,
            SourceType,
            UnitTypeTarget,
            UseSplit,
        )

        stub_prov = Provenance(source_type=SourceType.INFERRED, inferred_from=["stub"])
        stub_conf = Confidence(score=0.1, reasons=["pre-inference stub"])
        stub_programme = ProgrammeProposal(
            target_total_gfa_m2=1.0,
            use_split=UseSplit(
                residential_m2=1.0,
                productive_m2=0.0,
                office_m2=0.0,
                retail_horeca_m2=0.0,
                cultural_m2=0.0,
                social_m2=0.0,
                other_m2=0.0,
                rationale="stub",
                provenance=stub_prov,
                confidence=stub_conf,
            ),
            unit_mix=[
                UnitTypeTarget(
                    tenure="sociale_huur",
                    size_band="mixed",
                    fraction_of_total_dwellings=1.0,
                    rationale="stub",
                    provenance=stub_prov,
                    confidence=stub_conf,
                )
            ],
            reasoning_trace=["stub"],
            provenance=stub_prov,
            confidence=stub_conf,
        )
        pre_framework = _assemble_framework(
            project,
            extraction,
            stub_programme.model_dump(mode="json"),
            geo_data,
            source_documents=source_documents,
        )
        geo_obj = GeoContext.model_validate(geo_data) if geo_data else None
        logger.info("Running programme inference (expensive)…")
        programme_data = _run_programme(pre_framework, geo_obj, paths["programme"])
        fresh.append("programme")

    # ---------- Assemble the real framework ----------
    framework = _assemble_framework(
        project,
        extraction,
        programme_data,
        geo_data,
        source_documents=source_documents,
    )

    # ---------- Stage: IMRO cross-validation ----------
    if skip_cross_validate:
        cv_by_id = _load_json(paths["cross_validate"]) if paths["cross_validate"].exists() else {}
        cached.append("cross-validation")
    elif paths["cross_validate"].exists() and not force:
        cv_by_id = _load_json(paths["cross_validate"])
        cached.append("cross-validation")
    else:
        logger.info("Running IMRO cross-validation (expensive)…")
        cv_by_id = _run_cross_validate(framework, paths["cross_validate"])
        fresh.append("cross-validation")
    framework = _apply_cross_validation(framework, cv_by_id)

    # ---------- Cheap chain ----------
    kavel = _find_pdf(in_dir, ("kaveltekening", "verbeelding", "plankaart"))
    if kavel is None:
        typer.echo(
            f"No kaveltekening/verbeelding/plankaart PDF found in {in_dir}", err=True
        )
        raise typer.Exit(code=2)

    logger.info("Parsing geometry from {}", kavel.name)
    geometry_obj = parse_kaveltekening(kavel)
    _write_json(paths["geometry"], geometry_obj.model_dump(mode="json"))
    fresh.append("geometry")

    if geometry_obj.status == "ok":
        geometry_obj, recon_findings = reconcile_heights(framework, geometry_obj)
        _write_json(
            paths["reconciliation"],
            [f.model_dump(mode="json") for f in recon_findings],
        )
        fresh.append("reconciliation")
        framework = merge_geometry_into_framework(framework, geometry_obj)
        fresh.append("merge")

    from omrt_extractor.enrich_zones import enrich_zones, write_zone_summary, print_zone_table

    framework, zone_summaries = enrich_zones(framework)
    zone_summary_path = out_dir / "zone_programme_summary.json"
    write_zone_summary(zone_summaries, zone_summary_path)
    print_zone_table(zone_summaries)
    fresh.append("zone_enrichment")

    massings = generate_example_massings(framework, output_dir=out_dir)
    framework = framework.model_copy(update={"massings": massings})
    fresh.append("massings")

    # ---------- Stage: sanity validation (Scenario 1 Layer 5) ----------
    from omrt_extractor.validators import run_all_validations

    findings = run_all_validations(framework)
    sanity_path = out_dir / "sanity_report.json"
    _write_json(sanity_path, [f.model_dump(mode="json") for f in findings])
    fresh.append("sanity")
    if findings:
        logger.info("Sanity report: {} finding(s) at {}", len(findings), sanity_path)
        for f in findings[:10]:
            logger.warning("[{}] {}: {}", f.severity, f.constraint_name, f.message)
    else:
        logger.info("Sanity report: no physical-sense violations detected.")

    framework_path = write_grasshopper_handoff(framework, out_dir)
    fresh.append("output")

    # ---------- Summary ----------
    print()
    print(f"omrt run complete: project={project}")
    print(f"Cached/skipped: {', '.join(cached) if cached else '(none)'}")
    print(f"Ran fresh:      {', '.join(fresh)}")
    print(f"Output directory: {out_dir}/")
    print()
    print("Key files:")
    print(f"  {framework_path.name}        # structured design inputs")
    print("  summary.md            # human-readable handoff")
    print("  massing_inputs.json   # slim envelope for Grasshopper")
    geom_count = len(list((out_dir / "geometry").glob("*.compas")))
    mass_count = len(list((out_dir / "massings").glob("*.compas.json")))
    print(f"  geometry/             # {geom_count} .compas Polygons")
    print(f"  massings/             # {mass_count} example massings")
    print()
    print("Open the viewer: streamlit run viewer/streamlit_app.py")


@app.command()
def validate(framework_path: str) -> None:
    """Re-run sanity validators on an existing framework.json."""
    from omrt_extractor.schemas import ParametricFramework
    from omrt_extractor.validators import run_all_validations

    path = Path(framework_path).resolve()
    if not path.is_file():
        typer.echo(f"framework.json not found: {path}", err=True)
        raise typer.Exit(code=2)

    framework = ParametricFramework.model_validate_json(path.read_text())
    findings = run_all_validations(framework)
    out_path = path.parent / "sanity_report.json"
    _write_json(out_path, [f.model_dump(mode="json") for f in findings])

    if not findings:
        typer.echo(f"No physical-sense violations detected. Wrote {out_path}")
        return
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    typer.echo(f"{len(findings)} finding(s): {errors} error(s), {warnings} warning(s).")
    for f in findings:
        typer.echo(f"  [{f.severity}] {f.constraint_name}: {f.message}")
    typer.echo(f"Wrote {out_path}")


@app.command()
def archive(framework_path: str) -> None:
    """Mark a framework as reviewed and archive it."""
    typer.echo(f"TODO: implement archive on {framework_path}")


if __name__ == "__main__":
    app()
