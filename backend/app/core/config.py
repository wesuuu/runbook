from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/runbook"
    )
    secret_key: str = "dev-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    auth_enabled: bool = True

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

    model_config = {"env_prefix": "RUNBOOK_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
