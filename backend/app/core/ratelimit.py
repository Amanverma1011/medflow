import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.errors import AppError

_hits: dict[str, deque[float]] = defaultdict(deque)


def rate_limit(bucket: str, limit: int, window_seconds: int):
    """Sliding-window limiter keyed by client IP + bucket.

    ponytail: in-process memory, so limits are per worker. Move to Redis when
    running more than one backend replica.
    """

    def dependency(request: Request) -> None:
        key = f"{bucket}:{request.client.host if request.client else 'unknown'}"
        now, hits = time.monotonic(), _hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            retry = int(window_seconds - (now - hits[0])) + 1
            raise AppError(429, "Too many requests. Please slow down and try again shortly.",
                           headers={"Retry-After": str(retry)})
        hits.append(now)

    return dependency


def reset() -> None:
    _hits.clear()
