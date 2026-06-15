from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "alcohol-label-verifier"
    database_url: str = Field(default="postgresql+psycopg://label:label@postgres:5432/label")
    upload_dir: Path = Path("/data/uploads")
    static_dir: Path = Path("/app/frontend/dist")
    max_upload_mb: int = 15
    vision_provider: str = "noop"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-5.4-mini"
    openai_timeout_seconds: float = Field(default=10.0, gt=0)
    openai_image_max_side: int = Field(default=1600, ge=512)
    openai_image_jpeg_quality: int = Field(default=82, ge=30, le=95)
    review_token: str | None = None
    public_review_enabled: bool = False
    ocr_enabled: bool = True
    worker_idle_sleep_seconds: float = Field(default=0.5, gt=0)
    seed_demo_data: bool = False
    run_db_startup: bool = True
    sampled_review_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def review_token_required(self) -> bool:
        return bool(self.review_token) and not self.public_review_enabled


@lru_cache
def get_settings() -> Settings:
    return Settings()
