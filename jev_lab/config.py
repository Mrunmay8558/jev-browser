"""Configuration stays on the Python server; the key is never sent to the UI."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    typesafe_api_key: SecretStr = SecretStr("")
    jev_model: str = Field(default="jev-1.13.0", min_length=1)
    port: int = Field(default=4317, ge=1024, le=65535)
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.8-flash"
    browser_channel: str = "chrome"
    browser_profile_dir: Path = Path(".runtime/browser-profile")
    browser_dwell_ms: int = Field(default=450, ge=0, le=3000)
    jev_cdp_endpoint: str = ""
    jev_browser_target_id: str = ""

    @property
    def live_available(self) -> bool:
        return bool(self.typesafe_api_key.get_secret_value().strip())

    @property
    def agent_available(self) -> bool:
        return self.live_available and bool(self.gemini_api_key.get_secret_value().strip())


STATIC_DIR = Path(__file__).parent / "static"
