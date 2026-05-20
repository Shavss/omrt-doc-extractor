"""Central configuration for the OMRT doc-extractor pipeline.

Reads environment variables (with `.env` support via pydantic-settings)
and exposes a single `settings` object that other modules import.

The values here are deliberately the only place where model names,
thresholds, and external endpoints are configured. Hardcoding any of
these elsewhere violates the CLAUDE.md hard rules.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Pipeline configuration. Override via .env or environment variables.

    All field names use the OMRT_ prefix in env-var form, e.g.
    OMRT_EXTRACTION_MODEL=claude-sonnet-4-5
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="OMRT_",
        extra="ignore",
    )

    # LLM keys (read without prefix for compatibility with standard tooling)
    anthropic_api_key: str = Field(
        default="",
        description="Anthropic API key for Claude API calls.",
        validation_alias="ANTHROPIC_API_KEY",
    )
    stelselcatalogus_api_key: str = Field(
        default="",
        description=(
            "Optional API key for the Stelselcatalogus. Without this, the "
            "glossary seeder uses a 16-term hand-curated fallback."
        ),
        validation_alias="STELSELCATALOGUS_API_KEY",
    )

    # DSO API keys
    dso_general_api_key: str = Field(
        default="",
        description="General DSO API key for Stelselcatalogus and other DSO services.",
        validation_alias="DSO_GENERAL_API_KEY",
    )
    dso_rp_api_key: str = Field(
        default="",
        description="API key for DSO Ruimtelijke Plannen v4 API (cross-validation).",
        validation_alias="DSO_RP_API_KEY",
    )

    # DSO base URLs
    dso_rp_base_url: str = Field(
        default="https://ruimte.omgevingswet.overheid.nl/ruimtelijke-plannen/api/opvragen/v4",
        description="Base URL for the Ruimtelijke Plannen v4 API.",
        validation_alias="DSO_RP_BASE_URL",
    )

    # Models
    extraction_model: str = "claude-sonnet-4-6"
    inference_model: str = "claude-opus-4-7"

    # Confidence threshold for viewer highlighting; flagged below this value.
    confidence_threshold: float = 0.85

    # IMRO API cross-validation tolerance (relative)
    imro_cross_validation_tolerance: float = 0.05

    # Geo enrichment buffer radius in metres
    geo_buffer_radius_m: int = 2000

    # Render DPI for page preprocessing
    render_dpi: int = 200

    # Paths (resolved at import time)
    project_root: Path = Path(__file__).resolve().parents[2]

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def archive_dir(self) -> Path:
        return self.data_dir / "archive"


settings = Settings()
