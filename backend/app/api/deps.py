from dataclasses import dataclass

from fastapi import Query


@dataclass
class Page:
    page: int = Query(1, ge=1)
    size: int = Query(25, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

    def wrap(self, items: list, total: int) -> dict:
        return {"items": items, "total": total, "page": self.page, "size": self.size}


def like(q: str | None) -> str | None:
    """ILIKE pattern with user wildcards escaped."""
    if not q or not q.strip():
        return None
    escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
