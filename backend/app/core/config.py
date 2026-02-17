from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/runbook"
    )
    secret_key: str = "dev-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    model_config = {"env_prefix": "RUNBOOK_"}


settings = Settings()
