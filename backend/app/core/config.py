import warnings
from pathlib import Path

from pydantic import BaseModel, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from app.core.yaml_source import YamlConfigSettingsSource


class ProviderConfig(BaseModel):
    api_key: str = ""
    base_url: str = ""


class OfflineModeFeatureConfig(BaseModel):
    """Offline / PWA feature flag (TD-0082)."""

    enabled: bool = False


class OpenWetWareSourceConfig(BaseModel):
    """OpenWetWare protocol source (F-0084). Default-on within the master flag."""

    enabled: bool = True
    request_timeout_seconds: float = 10.0
    rate_limit_per_minute: int = 10


class ProtocolsIoSourceConfig(BaseModel):
    """protocols.io protocol source (F-0090). Opt-in; needs an access token."""

    enabled: bool = False
    access_token: str = ""  # long-lived API token — secret, env-var only
    request_timeout_seconds: float = 10.0
    rate_limit_per_minute: int = 10


class RegistrationFeatureConfig(BaseModel):
    """Self-service registration flag (F-0091). Default-on; flip OFF in prod."""

    enabled: bool = True


class ExternalProtocolsFeatureConfig(BaseModel):
    """External protocol knowledgebase feature flag (F-0084, F-0090).

    `enabled` is the master capability switch. Each source has its own
    nested sub-block with an independent enable flag and throttle. A source
    is live iff the master flag AND that source's flag are both on.
    """

    enabled: bool = False
    openwetware: OpenWetWareSourceConfig = OpenWetWareSourceConfig()
    protocols_io: ProtocolsIoSourceConfig = ProtocolsIoSourceConfig()


class FeaturesConfig(BaseModel):
    """Top-level feature-flag namespace.

    Configure via `settings.yaml` (preferred) or env vars using the
    `BATCHRITE_FEATURES__<FEATURE>__<FIELD>` form.
    """

    offline_mode: OfflineModeFeatureConfig = OfflineModeFeatureConfig()
    external_protocols: ExternalProtocolsFeatureConfig = (
        ExternalProtocolsFeatureConfig()
    )
    registration: RegistrationFeatureConfig = RegistrationFeatureConfig()


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite"
    )
    secret_key: str = "dev-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    auth_enabled: bool = True
    legal_gate_enabled: bool = True  # env: BATCHRITE_LEGAL_GATE_ENABLED

    # OAuth Configuration
    oauth_google_client_id: str = ""
    oauth_google_client_secret: str = ""
    oauth_microsoft_client_id: str = ""
    oauth_microsoft_client_secret: str = ""
    oauth_microsoft_tenant: str = "common"
    oauth_callback_url: str = "http://localhost:5173/auth/callback"

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
    ai_chat_provider: str = ""
    ai_chat_model: str = ""
    ai_chat_subagent_provider: str = ""
    ai_chat_subagent_model: str = ""
    ai_chat_summary_provider: str = ""
    ai_chat_summary_model: str = ""
    ai_protocol_generation_provider: str = ""
    ai_protocol_generation_model: str = ""
    ai_protocol_creation_provider: str = ""
    ai_protocol_creation_model: str = ""
    ai_protocol_editing_provider: str = ""
    ai_protocol_editing_model: str = ""
    ai_template_convert_provider: str = ""
    ai_template_convert_model: str = ""

    # Provider-level credentials (env vars like BATCHRITE_OPENROUTER__API_KEY,
    # BATCHRITE_OLLAMA__BASE_URL). Only providers currently in use are listed;
    # add others (anthropic, openai, etc.) one line at a time when needed.
    openrouter: ProviderConfig = ProviderConfig()
    ollama: ProviderConfig = ProviderConfig()
    anthropic: ProviderConfig = ProviderConfig()

    # Template conversion settings
    template_convert_max_tool_calls: int = 25

    # Task runner backend: "thread" (default) — future: "kubernetes", "celery"
    task_runner_backend: str = "thread"
    task_runner_pool_size: int = 4

    # Background-job dispatch (TD-0085).
    # "local" runs jobs in-process via the TaskRunner;
    # "cloud-gpu" will dispatch to a dedicated GPU service.
    background_handler: str = "local"  # "local" | "cloud-gpu"

    # Phase 3: how often the recovery loop sweeps for stalled jobs/docs
    # and retries due notification deliveries. The startup sweep still
    # runs once on lifespan boot for job/doc recovery; the delivery-retry
    # sweep is loop-only. Set to 0 to disable the loop entirely — this
    # also disables notification delivery retries.
    recovery_interval_seconds: int = 90

    # Docling extractor (TD-0085) — paths to the standalone ext/ project's
    # interpreter and CLI entrypoint. Defaults assume the repo layout
    # (backend/ and ext/ are siblings); override via env vars in deploy.
    docling_script_python: str = str(
        Path(__file__).resolve().parents[3]
        / "ext"
        / "docling-extractor"
        / ".venv"
        / "bin"
        / "python"
    )
    docling_script_path: str = str(
        Path(__file__).resolve().parents[3] / "ext" / "docling-extractor" / "extract.py"
    )
    docling_num_threads: int = 4

    # Chat agent skills directory
    skills_dir: str = str(
        Path(__file__).resolve().parent.parent / "services" / "ai" / "skills"
    )

    # App-help corpus directory (F-0089). Repo-root docs/user-guide — an
    # absolute path computed from __file__ so it resolves regardless of the
    # process CWD (backend/ at runtime). parents[3] is the repo root, the
    # same anchor docling_script_path uses. Override via env in deploy.
    user_guide_dir: str = str(
        Path(__file__).resolve().parents[3] / "docs" / "user-guide"
    )

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
        "gpt-oss:120b-cloud": 131072,
        "command-r": 131072,
        "command-r-plus": 131072,
        "gpt-oss": 131072,
        # Cloud providers
        "claude-3-5-sonnet": 200000,
        "claude-3-5-haiku": 200000,
        "claude-3-opus": 200000,
        "claude-4": 200000,
        # Claude 4 family + OpenRouter-style anthropic/ prefixes
        "claude-sonnet-4": 200000,
        "claude-opus-4": 200000,
        "claude-haiku-4": 200000,
        "anthropic/claude-sonnet-4": 200000,
        "anthropic/claude-opus-4": 200000,
        "anthropic/claude-haiku-4": 200000,
        "anthropic/claude-3-5-sonnet": 200000,
        "anthropic/claude-3-5-haiku": 200000,
        "anthropic/claude-3-opus": 200000,
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-4-turbo": 128000,
        "gpt-4": 8192,
        "gpt-3.5-turbo": 16385,
        "gemini-1.5-pro": 1048576,
        "gemini-1.5-flash": 1048576,
        "gemini-2.0-flash": 1048576,
        "moonshotai/kimi-k2": 131072,
        "kimi-k2:1t-cloud": 131072,
        "kimi-k2.6:cloud": 131072,
        "gemma4:31b-cloud": 131072,
        "qwen3-coder:480b-cloud": 262144,
        "deepseek-v3.1:671b-cloud": 131072,
        "minimax-m2.7:cloud": 200000,
        "qwen3.6:35b": 131072,
    }

    # Debug mode — enables dev-only endpoints (webhook echo, etc.)
    debug: bool = False

    # Feature flags (TD-0082). Nested so `settings.yaml` and env vars share
    # the same shape: `BATCHRITE_FEATURES__OFFLINE_MODE__ENABLED=true`.
    features: FeaturesConfig = FeaturesConfig()

    # Stripe billing (added F-0019a) -- all optional; endpoints return
    # 503 with a clear message when any required field is unset.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_essentials_price_id: str = ""
    stripe_pro_price_id: str = ""
    essentials_trial_days: int = 30
    stripe_portal_return_url: str = "/settings?tab=billing"

    # Seat caps per tier (added F-0019a). Enterprise has no cap;
    # handled in code by `get_seat_limit(tier)` returning None.
    seat_limit_essentials: int = 5
    seat_limit_pro: int = 25

    # Loops CRM (added F-0019c). Empty means lifecycle emissions no-op.
    loops_api_key: str = ""
    loops_base_url: str = "https://app.loops.so/api/v1"
    loops_request_timeout_seconds: float = 5.0

    # Extraction heartbeat (TD-0085). The subprocess posts to the backend
    # every interval_seconds; after max_misses consecutive missed beats the
    # watchdog kills the process and marks the document FAILED.
    extraction_heartbeat_interval_seconds: int = 10
    extraction_heartbeat_max_misses: int = 3
    extraction_heartbeat_base_url: str = "http://localhost:8000"

    model_config = {
        "env_prefix": "BATCHRITE_",
        "env_file": ".env",
        "extra": "ignore",
        "env_nested_delimiter": "__",
    }

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


settings = Settings()
