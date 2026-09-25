"""Limitador sencillo de intentos de inicio de sesión (en memoria)."""
import time
from collections import defaultdict


class AttemptLimiter:
    def __init__(self, limit=8, window_seconds=600):
        self.limit = limit
        self.window = window_seconds
        self._failures = defaultdict(list)

    def _recent(self, key):
        cutoff = time.monotonic() - self.window
        self._failures[key] = [t for t in self._failures[key] if t > cutoff]
        return self._failures[key]

    def blocked(self, key):
        return len(self._recent(key)) >= self.limit

    def register_failure(self, key):
        self._recent(key).append(time.monotonic())

    def reset(self, key=None):
        if key is None:
            self._failures.clear()
        else:
            self._failures.pop(key, None)


login_limiter = AttemptLimiter()
