import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_name: str = "PPT Generation Pipeline"
    api_prefix: str = "/v1"
    secret_key: str = "change-me"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Redis and job queue
    redis_url: str = "redis://localhost:6379/0"
    queue_name: str = "ppt_jobs"

    # Output directories
    # Docker Compose overrides these with absolute container paths.
    output_dir: str = "./generated"
    temp_dir: str = "./tmp"

    # Temporal workflow engine
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "ppt_generation"
    temporal_workflow_timeout_hours: int = 2

    # Claim-check threshold, not the Temporal server gRPC limit. Keep low for fan-out.
    temporal_payload_inline_bytes: int = Field(default=16384, ge=0, le=16384)
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "pptadmin"
    minio_secret_key: str = "change-this-minio-password"
    minio_secure: bool = False
    minio_payload_bucket: str = "ppt-temporal-payloads"
    minio_output_bucket: str = "ppt-generated"

    # Job retention and idempotency
    job_ttl_hours: int = 24
    idempotency_ttl_min: int = 60
    content_cache_enabled: bool = True
    content_cache_ttl_hours: int = 168

    # Input limits
    max_input_chars: int = 500000
    max_input_tokens: int = 100000
    max_upload_mb: int = 20

    # Input chunking and context windows
    window_tokens: int = 3000
    window_overlap_msgs: int = 1
    chunk_tokens: int = 3000

    # Slide generation
    slides_min: int = 4
    slides_max: int = 20
    default_slide_count: int = 8
    max_output_slides: int = 20

    # Concurrency and retries
    slide_concurrency: int = 4
    llm_concurrency: int = 4
    build_retries: int = 1
    qa_max_rounds: int = 1
    qa_concurrency: int = 2

    # Charts
    max_chart_count: int = 8

    # File retention
    file_ttl_hours: int = 24

    # GLM OpenAI-compatible endpoint
    glm_base_url: str = "http://localhost:8001/v1"
    glm_api_key: str = "not-needed"
    glm_model: str = "glm"

    # Gemma OpenAI-compatible endpoint
    # For Ollama running directly on your Mac, Docker Compose
    # should override this with host.docker.internal:11434.
    gemma_base_url: str = "http://localhost:11434/v1"
    gemma_api_key: str = "not-needed"
    gemma_model: str = "gemma3:4b"
    gemma_vision_model: str = "gemma3:4b"

    # LLM request configuration
    llm_timeout_seconds: int = 180
    planner_temperature: float = 0.1
    planner_max_tokens: int = 5000
    parser_max_tokens: int = 1200
    digest_max_tokens: int = 2500
    builder_temperature: float = 0.2
    builder_max_tokens: int = 2500
    review_max_tokens: int = 1800
    qa_max_tokens: int = 800
    llm_retries: int = 2

    # Visual quality checks and export
    enable_theme_background_matching: bool = False
    enable_visual_qa: bool = False
    enable_pdf_export: bool = True
    enable_thumbnails: bool = True
    min_contrast: float = 4.5
    min_quality_score: float = 50.0

    @property
    def output_path(self) -> Path:
        path = Path(self.output_dir).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def temp_path(self) -> Path:
        path = Path(self.temp_dir).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
