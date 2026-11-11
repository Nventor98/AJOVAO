
from app.shared.celery_app import celery_app
from app.shared.jobs import enqueue, job


def test_inline_job_executes_when_enqueued() -> None:
    results: list[int] = []

    @job
    def add_numbers(a: int, b: int) -> None:
        results.append(a + b)

    result = enqueue(add_numbers, 4, 6)

    assert result is None
    assert results == [10]


def test_inline_job_preserves_function_name() -> None:
    @job
    def sample_job() -> str:
        return "completed"

    assert sample_job.__name__ == "sample_job"
    assert enqueue(sample_job) == "completed"


def test_celery_job_is_submitted_without_running_inline(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "job_backend", "celery")

    submitted: dict[str, object] = {}
    expected_result = object()

    @job
    def celery_job(value: str) -> str:
        raise AssertionError("Celery job must not execute inline")

    def fake_delay(*args, **kwargs):
        submitted["args"] = args
        submitted["kwargs"] = kwargs
        return expected_result

    monkeypatch.setattr(celery_job, "delay", fake_delay)

    result = enqueue(celery_job, "hello", priority=3)

    assert result is expected_result
    assert submitted["args"] == ("hello",)
    assert submitted["kwargs"] == {"priority": 3}


def test_celery_task_is_registered_with_expected_name() -> None:
    from app.shared.celery_app import celery_app

    @job
    def registration_check() -> None:
        pass

    expected_name = (
    "naijalife.jobs.test_jobs.registration_check"
)

    assert registration_check.name == expected_name
    assert expected_name in celery_app.tasks
    assert celery_app.tasks[expected_name].name == expected_name
