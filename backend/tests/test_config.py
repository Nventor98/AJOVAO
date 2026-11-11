
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

def test_inline_job_backend_is_allowed_in_development() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        job_backend="inline",
    )
    assert settings.job_backend == "inline"


def test_celery_job_backend_is_allowed_in_development() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        job_backend="celery",
    )
    assert settings.job_backend == "celery"


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_inline_job_backend_is_rejected_outside_development(
    environment: str,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env=environment,
            secret_key="a-valid-test-secret-key-with-more-than-32-bytes",
            job_backend="inline",
        )


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_celery_job_backend_is_required_outside_development(
    environment: str,
) -> None:
    settings = Settings(
        _env_file=None,
        app_env=environment,
        secret_key="a-valid-test-secret-key-with-more-than-32-bytes",
        job_backend="celery",
    )
    assert settings.job_backend == "celery"


def test_invalid_job_backend_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="development",
            job_backend="unknown",
        )
