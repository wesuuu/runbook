import warnings

from pydantic import BaseModel, model_validator
from pydantic_settings import BaseSettings


class ProviderConfig(BaseModel):
    api_key: str = ""
    base_url: str = ""


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite"
    )
    secret_key: str = "dev-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    auth_enabled: bool = True

    # SMTP / Email
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "noreply@batchrite.local"
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_tls: bool = False

    # Verification
    verification_token_ttl_days: int = 7
    verification_resend_limit: int = 3
    verification_resend_window_minutes: int = 10
    verification_temp_token_minutes: int = 60

    # Invitations
    invitation_ttl_days: int = 7

    # URLs (for verification email links and redirects)
    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"

    @model_validator(mode="after")
    def _warn_insecure_defaults(self) -> "Settings":
        if not self.debug:
            if self.secret_key.startswith("dev-"):
                warnings.warn(
                    "BATCHRITE_SECRET_KEY is using the default dev key. "
                    "Set a secure secret via BATCHRITE_SECRET_KEY env var.",
                    stacklevel=1,
                )
            if "postgres:postgres@localhost" in self.database_url:
                warnings.warn(
                    "BATCHRITE_DATABASE_URL is using default local credentials. "
                    "Set an explicit database URL via BATCHRITE_DATABASE_URL env var.",
                    stacklevel=1,
                )
        return self


    # AI env var fallbacks (used only before DB is configured)
    ai_vision_provider: str = ""
    ai_vision_model: str = ""
    ai_audio_provider: str = ""
    ai_audio_model: str = ""
    ai_text_provider: str = ""
    ai_text_model: str = ""
    ai_embedding_provider: str = ""
    ai_embedding_model: str = ""
    ai_doc_structure_provider: str = ""
    ai_doc_structure_model: str = ""
    ai_chat_provider: str = ""
    ai_chat_model: str = ""
    ai_protocol_generation_provider: str = ""
    ai_protocol_generation_model: str = ""
    ai_template_convert_provider: str = ""
    ai_template_convert_model: str = ""

    # Provider-level credentials (env vars like BATCHRITE_OPENROUTER__API_KEY,
    # BATCHRITE_OLLAMA__BASE_URL). Only providers currently in use are listed;
    # add others (anthropic, openai, etc.) one line at a time when needed.
    openrouter: ProviderConfig = ProviderConfig()
    ollama: ProviderConfig = ProviderConfig()

    # Template conversion settings
    template_convert_max_tool_calls: int = 25

    # Task runner backend: "thread" (default) — future: "kubernetes", "celery"
    task_runner_backend: str = "thread"
    task_runner_pool_size: int = 4

    # Chat agent skills directory
    skills_dir: str = "skills"

    # Chat context window management
    max_message_length: int = 10000
    compaction_threshold: float = 0.6
    context_window_defaults: dict = {
        # Ollama / small models
        "llama3": 8192,
        "llama3.1": 131072,
        "llama3.2": 131072,
        "gemma3": 8192,
        "gemma2": 8192,
        "phi3": 4096,
        "phi4": 16384,
        "qwen3": 32768,
        "qwen3.5": 32768,
        "qwen2.5": 32768,
        "mistral": 32768,
        "mixtral": 32768,
        "deepseek-r1": 65536,
        "command-r": 131072,
        "command-r-plus": 131072,
        # Cloud providers
        "claude-3-5-sonnet": 200000,
        "claude-3-5-haiku": 200000,
        "claude-3-opus": 200000,
        "claude-4": 200000,
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-4-turbo": 128000,
        "gpt-4": 8192,
        "gpt-3.5-turbo": 16385,
        "gemini-1.5-pro": 1048576,
        "gemini-1.5-flash": 1048576,
        "gemini-2.0-flash": 1048576,
    }

    # Debug mode — enables dev-only endpoints (webhook echo, etc.)
    debug: bool = False

    model_config = {
        "env_prefix": "BATCHRITE_",
        "env_file": ".env",
        "extra": "ignore",
        "env_nested_delimiter": "__",
    }


settings = Settings()
