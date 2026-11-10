from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence, TypeVar

from fastapi import Query

from app.core.config import settings
from app.shared.responses import ok

T = TypeVar("T")


@dataclass
class Pagination:
    page: int = 1
    page_size: int = 20
    total: int = 0

    @property
    def skip(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def max_page(self) -> int:
        if self.total == 0:
            return 1
        return max(1, (self.total + self.page_size - 1) // self.page_size)


def paginate(items: Sequence[T], *, page: int, page_size: int, total: int | None = None) -> tuple[list[T], Pagination]:
    page = max(1, page)
    page_size = min(max(1, page_size), settings.max_page_size)
    if total is None:
        total = len(items)
    slice_start = (page - 1) * page_size
    slice_stop = slice_start + page_size
    return list(items[slice_start:slice_stop]), Pagination(page=page, page_size=page_size, total=total)


def paginated_ok(data: Any, *, page: int = 1, page_size: int = 20, total: int | None = None) -> dict[str, Any]:
    items, pagination = paginate(data, page=page, page_size=page_size, total=total)
    return ok(
        items,
        meta={
            "pagination": {
                "page": pagination.page,
                "page_size": pagination.page_size,
                "total": pagination.total,
                "max_page": pagination.max_page,
            }
        },
    )
