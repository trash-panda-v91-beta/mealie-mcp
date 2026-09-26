"""Configuration management for the Mealie MCP server."""

import logging

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Environment-driven configuration (reads .env and MEALIE_* vars)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mealie_base_url: str | None = None
    mealie_api_token: str | None = None
    log_level: str = "INFO"
    rate_limit_per_second: float = 10.0
    rate_limit_burst: int = 10
    # Opt into plaintext http base URLs (e.g. cluster-internal .svc.cluster.local).
    # Default stays https-only so the API token is never sent in clear.
    allow_insecure_http: bool = False

    @model_validator(mode="after")
    def _validate(self) -> Config:
        base = self.mealie_base_url or ""
        errors: list[str] = []
        if not base:
            errors.append(
                "MEALIE_BASE_URL environment variable is required. Please set it to your Mealie instance URL."
            )
        elif not base.startswith("https://") and not self.allow_insecure_http:
            errors.append(
                f"MEALIE_BASE_URL must use HTTPS for security (or set ALLOW_INSECURE_HTTP=true). Got: {base[:50]}"
            )
        if not self.mealie_api_token:
            errors.append(
                "MEALIE_API_TOKEN environment variable is required. "
                "Create one in Mealie under user settings > API Tokens."
            )

        if errors:
            raise ValueError("Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

        self.mealie_base_url = base.rstrip("/")
        return self

    def configure_logging(self) -> None:
        """Configure logging based on log level."""
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper(), logging.INFO),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )


# Global configuration instance
config = Config()
