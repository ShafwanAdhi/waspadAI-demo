from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration loaded from the project-level .env file."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "WaspadAI"
    app_env: str = "development"
    waspadai_api_keys: str = ""

    groq_api_key: str = ""
    groq_vision_model: str = "qwen/qwen3.6-27b"
    groq_planner_model: str = "openai/gpt-oss-20b"
    groq_escalation_model: str = "openai/gpt-oss-120b"
    groq_final_model: str = "qwen/qwen3.6-27b"
    groq_timeout_seconds: float = 90.0
    groq_vision_max_tokens: int = 900
    groq_planner_max_tokens: int = Field(default=1800, ge=600, le=4000)
    groq_review_max_tokens: int = Field(default=700, ge=400, le=4000)
    groq_final_max_tokens: int = Field(default=900, ge=500, le=4000)
    planner_review_enabled: bool = False
    groq_rate_limit_reference_plan: Literal["free", "developer"] = "free"
    tavily_api_key: str = ""
    tavily_timeout_seconds: float = Field(default=20.0, ge=3.0, le=60.0)
    web_search_max_queries: int = Field(default=3, ge=1, le=6)
    web_search_results_per_query: int = Field(default=3, ge=1, le=5)
    web_search_excerpt_chars: int = Field(default=800, ge=200, le=1800)
    max_evidence_items_for_verifier: int = 6
    max_evidence_excerpt_chars: int = 650

    tesseract_cmd: str = ""
    tesseract_lang: str = "ind+eng"
    max_upload_mb: int = 8
    min_image_width: int = Field(default=64, ge=1, le=4096)
    min_image_height: int = Field(default=64, ge=1, le=4096)
    max_image_width: int = Field(default=6000, ge=512, le=12000)
    max_image_height: int = Field(default=6000, ge=512, le=12000)
    max_image_pixels: int = Field(default=30_000_000, ge=262_144, le=80_000_000)
    max_image_question_chars: int = Field(default=500, ge=1, le=2000)
    min_text_chars: int = Field(default=10, ge=1, le=1000)
    max_text_chars: int = Field(default=25_000, ge=1000, le=100_000)
    max_case_urls: int = Field(default=10, ge=1, le=50)
    max_planned_claims: int = Field(default=8, ge=1, le=20)
    planner_case_max_chars: int = Field(default=6000, ge=1500, le=16000)
    planner_rule_limit: int = Field(default=6, ge=2, le=12)
    planner_rule_content_chars: int = Field(default=240, ge=100, le=500)
    evidence_sufficiency_threshold: float = 0.58

    # Local-only, privacy-filtered pipeline observability. Traces are held in
    # memory and are intentionally disabled when APP_ENV=production.
    debug_trace_enabled: bool = True
    debug_trace_max_records: int = Field(default=50, ge=1, le=500)
    debug_trace_max_value_chars: int = Field(default=12_000, ge=1000, le=100_000)

    # Local rulebook RAG. The compiled corpus is generated from rulebook/*.txt.
    rulebook_compiled_dir: Path = PROJECT_ROOT / "rulebook" / "compiled"
    rulebook_max_rules: int = Field(default=12, ge=4, le=30)
    rulebook_candidate_k: int = Field(default=30, ge=12, le=100)
    rulebook_cache_size: int = Field(default=128, ge=0, le=4096)
    rulebook_min_score: float = Field(default=0.12, ge=0, le=1)

    # Optional production adapters.
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection: str = "factcheck_knowledge"
    embedding_api_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""

    @property
    def debug_enabled(self) -> bool:
        return self.debug_trace_enabled and self.app_env.strip().lower() != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
