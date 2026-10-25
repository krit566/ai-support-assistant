"""Per-key rate limit for the public chat endpoint: a sliding window of the last 60 seconds.

Kept in process memory: correct for one server process. With several processes each would allow the full limit, so
a shared store (Redis INCR with expiry) is the next step; see the README.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindow:
    def __init__(self, window_seconds: float = 60.0, clock=time.monotonic):
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int) -> tuple[bool, int]:
        """(allowed, seconds until the next request would be allowed)"""
        now = self.clock()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= limit:
                return False, max(1, int(q[0] + self.window - now + 0.999))
            q.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindow()
