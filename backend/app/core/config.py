import warnings

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/runbook"
    )
    secret_key: str = "dev-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    auth_enabled: bool = True

    @model_validator(mode="after")
    def _warn_insecure_defaults(self) -> "Settings":
        if not self.debug:
            if self.secret_key.startswith("dev-"):
                warnings.warn(
                    "RUNBOOK_SECRET_KEY is using the default dev key. "
                    "Set a secure secret via RUNBOOK_SECRET_KEY env var.",
                    stacklevel=1,
                )
            if "postgres:postgres@localhost" in self.database_url:
                warnings.warn(
                    "RUNBOOK_DATABASE_URL is using default local credentials. "
                    "Set an explicit database URL via RUNBOOK_DATABASE_URL env var.",
                    stacklevel=1,
                )
        return self

    # Image storage
    image_storage_path: str = "./uploads/images"

    # AI env var fallbacks (used only before DB is configured)
    ai_vision_provider: str = ""
    ai_vision_model: str = ""
    ai_vision_api_key: str = ""
    ai_vision_base_url: str = ""
    ai_audio_provider: str = ""
    ai_audio_model: str = ""
    ai_audio_api_key: str = ""
    ai_audio_base_url: str = ""
    ai_text_provider: str = ""
    ai_text_model: str = ""
    ai_text_api_key: str = ""
    ai_text_base_url: str = ""

    # Debug mode — enables dev-only endpoints (webhook echo, etc.)
    debug: bool = False

    model_config = {"env_prefix": "RUNBOOK_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
