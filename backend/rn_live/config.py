from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RN_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./data/rn-live.db"
    storage_dir: Path = Path("data/media")
    max_upload_bytes: int = 1_000_000_000
    max_duration_ms: int = 3_600_000
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    hf_token: str = ""
    diarization_model: str = "pyannote/speaker-diarization-community-1"
    lease_seconds: int = 120
    openrouter_api_key: str = Field(default="", validation_alias=AliasChoices("OPENROUTER_API_KEY", "RN_OPENROUTER_API_KEY"))
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1", validation_alias=AliasChoices("OPENROUTER_BASE_URL", "RN_OPENROUTER_BASE_URL"))
    openrouter_model: str = Field(default="openrouter/free", validation_alias=AliasChoices("OPENROUTER_MODEL", "RN_OPENROUTER_MODEL"))
    openrouter_free_only: bool = Field(default=True, validation_alias=AliasChoices("OPENROUTER_FREE_ONLY", "RN_OPENROUTER_FREE_ONLY"))
    openrouter_timeout_seconds: float = Field(default=45.0, validation_alias=AliasChoices("OPENROUTER_TIMEOUT_SECONDS", "RN_OPENROUTER_TIMEOUT_SECONDS"))
    openrouter_http_referer: str = Field(default="", validation_alias=AliasChoices("OPENROUTER_HTTP_REFERER", "RN_OPENROUTER_HTTP_REFERER"))
    openrouter_app_title: str = Field(default="RN-live", validation_alias=AliasChoices("OPENROUTER_APP_TITLE", "RN_OPENROUTER_APP_TITLE"))
