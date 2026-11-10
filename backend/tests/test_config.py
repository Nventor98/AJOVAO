
import pytest
from pydantic import ValidationError

from app.core.config import DEVELOPMENT_SECRET_KEY, Settings


def test_development_secret_key_is_at_least_32_bytes() -> None:
    assert len(DEVELOPMENT_SECRET_KEY.encode("utf-8")) >= 32


def test_development_secret_key_is_allowed_in_development() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        secret_key=DEVELOPMENT_SECRET_KEY,
    )
    assert settings.secret_key == DEVELOPMENT_SECRET_KEY


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_development_secret_key_is_rejected_outside_development(
    environment: str,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env=environment,
            secret_key=DEVELOPMENT_SECRET_KEY,
        )


def test_short_secret_is_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            secret_key="short-secret",
        )
