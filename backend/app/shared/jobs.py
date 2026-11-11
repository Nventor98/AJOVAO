
from __future__ import annotations

from typing import Any, Callable, TypeVar

from app.core.config import settings
from app.shared.celery_app import celery_app


F = TypeVar("F", bound=Callable[..., Any])


def job(func: F) -> Callable[..., Any]:
    """Register a function as a background job."""

    task_name = f"naijalife.jobs.{func.__module__}.{func.__name__}"

    return celery_app.task(name=task_name)(func)


def enqueue(
    task: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Submit a registered job using the configured backend."""

    if settings.job_backend.lower() == "celery":
        delay = getattr(task, "delay", None)

        if not callable(delay):
            raise TypeError(
                "Celery jobs must be registered with @job before enqueueing."
            )

        return delay(*args, **kwargs)

    run = getattr(task, "run", None)

    if callable(run):
        return run(*args, **kwargs)

    return task(*args, **kwargs)