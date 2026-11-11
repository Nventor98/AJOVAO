from __future__ import annotations

from functools import lru_cache
from decimal import Decimal
import ipaddress

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_SECRET_KEY = "naijalife-development-only-key-not-for-production"


class Settings(BaseSettings):
    app_name: str = Field(default="NaijaLife AI")
    app_env: str = Field(default="development")
    debug: bool = Field(default=False)
    secret_key: str = Field(default=DEVELOPMENT_SECRET_KEY)
    jwt_algorithm: str = Field(default="HS256")
    access_token_ttl_minutes: int = Field(default=60)
    phone_verification_ttl_minutes: int = Field(default=10)
    phone_verification_max_attempts: int = Field(default=5)
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None
    price_index_min_samples: int = Field(default=5, ge=2)
    price_index_min_sources: int = Field(default=2, ge=2)
    price_observation_max_age_days: int = Field(default=30, ge=1)
    savings_baseline_max_age_days: int = Field(default=30, ge=1)
    savings_baseline_min_samples: int = Field(default=5, ge=2)
    savings_baseline_min_sources: int = Field(default=2, ge=2)
    savings_baseline_radius_km: Decimal = Field(default=Decimal("50"), gt=0)
    price_anomaly_ratio: Decimal = Field(default=Decimal("3"), gt=1)
    demand_signal_min_households: int = Field(default=0, ge=0)

    database_url: str = Field(default="sqlite:///./naijalife.db")
    redis_url: str = Field(default="redis://localhost:6379/0")
    job_backend: str = Field(default="inline")
    trusted_proxies: list[str] = Field(default_factory=lambda: ["127.0.0.1", "::1"])

    max_page_size: int = Field(default=100)
    default_page_size: int = Field(default=20)

    model_config = SettingsConfigDict(
        env_prefix="NAIJALIFE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("trusted_proxies")
    @classmethod
    def trusted_proxy_ranges_are_valid(cls, value: list[str]) -> list[str]:
        for proxy in value:
            try:
                ipaddress.ip_network(proxy, strict=False)
            except ValueError as exc:
                raise ValueError(f"Invalid trusted proxy address or network: {proxy}") from exc
        return value

    @model_validator(mode="after")
    def reject_placeholder_production_secret(self) -> "Settings":
        if self.app_env.lower() in {"stage", "staging", "prod", "production"}:
            if (
                self.secret_key == DEVELOPMENT_SECRET_KEY
                or self.secret_key in {
                    "",
                    "change-me-in-production",
                    "secret",
                    "changeme",
                }
                or len(self.secret_key.encode("utf-8")) < 32
            ):
                raise ValueError(
                    "NAIJALIFE_SECRET_KEY must be a unique secret "
                    "of at least 32 bytes outside development."
                )
        if self.app_env.lower() in {"stage", "staging", "prod", "production"}:
            if self.job_backend.lower() != "celery":
                raise ValueError(
                    "NAIJALIFE_JOB_BACKEND must be 'celery' "
                    "outside development."
                )

        if self.job_backend.lower() not in {"inline", "celery"}:
            raise ValueError(
                "NAIJALIFE_JOB_BACKEND must be either 'inline' or 'celery'."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
TRUSTED_PROXIES = settings.trusted_proxies
