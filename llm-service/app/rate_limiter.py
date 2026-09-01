"""
rate_limiter.py
Auth plan step 13: per-user_id request budget. In-memory, fixed-window
counter -- the simplest thing that actually enforces RATE_LIMIT_PER_MINUTE
(the knob added in step 9, ahead of this middleware, specifically so it
would already exist by the time this landed) without pulling in a new
dependency (Redis, etc.) for a service this small.

Fixed window, not sliding: a user's count resets at the top of each
wall-clock minute rather than a rolling 60s lookback. This is deliberately
simpler than a sliding window / token bucket -- the tradeoff is it allows
a burst of up to ~2x the limit across a window boundary (e.g. the full
budget at 0:59, then the full budget again at 1:00). Acceptable for this
service's actual threat model (protecting llama.cpp/geometry-service
capacity from a runaway client loop, not billing-grade metering) --
tighten to a sliding window or token bucket later if real usage shows the
boundary burst matters.

Thread safety: guarded by a plain threading.Lock, same pattern as
store.py's ProjectStore._cursor() -- FastAPI/uvicorn can service requests
across multiple threads (sync dependencies run in a threadpool), so this
can't assume single-threaded access even though the app itself is async.

Scope -- read before deploying more than one replica: in-memory means the
counter resets on container restart and is NOT shared across replicas.
Fine for the current single-instance deployment (docker-compose.yml runs
exactly one llm-service container); a real multi-instance deployment
needs a shared counter (Redis INCR + EXPIRE is the standard approach)
instead of this class -- don't scale llm-service horizontally without
swapping this out first, or per-instance limits will silently multiply
the effective budget.
"""

from __future__ import annotations
import threading
import time


class RateLimiter:
    """Usage:
        limiter = RateLimiter(limit_per_minute=60)
        allowed, retry_after = limiter.check(user_id)
        if not allowed:
            # reject with 429, Retry-After: retry_after seconds
    """

    def __init__(self, limit_per_minute: int):
        # <= 0 disables rate limiting entirely -- check() always allows.
        # An explicit off-switch without touching any call site, same
        # spirit as SESSION_LIFETIME_HOURS being None meaning "never
        # expires" over in store.py.
        self.limit_per_minute = limit_per_minute
        self._lock = threading.Lock()
        # user_id -> (window_start_minute, count)
        self._counters: dict[str, tuple[int, int]] = {}

    def check(self, user_id: str) -> tuple[bool, int]:
        """Increments this user's count for the current window and
        returns (allowed, retry_after_seconds). retry_after_seconds is
        only meaningful when allowed is False -- seconds remaining until
        the current fixed window rolls over."""
        if self.limit_per_minute <= 0:
            return True, 0

        now = time.time()
        window = int(now // 60)
        retry_after = 60 - int(now % 60)

        with self._lock:
            stored_window, count = self._counters.get(user_id, (window, 0))
            if stored_window != window:
                # new window -- reset rather than accumulate a stale count
                stored_window, count = window, 0
            count += 1
            self._counters[user_id] = (stored_window, count)

            if count > self.limit_per_minute:
                return False, retry_after
            return True, 0

    def reset(self, user_id: str | None = None) -> None:
        """Ops/testing helper -- clears one user's counter, or all of them
        if user_id is omitted. Not called from any production code path."""
        with self._lock:
            if user_id is None:
                self._counters.clear()
            else:
                self._counters.pop(user_id, None)
