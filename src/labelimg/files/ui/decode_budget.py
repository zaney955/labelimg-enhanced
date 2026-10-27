"""One heavy decode at a time, with foreground priority and cancellable waits."""
from concurrent.futures import CancelledError
from collections import Counter
from contextlib import contextmanager
import threading


class DecodeBudget:
    def __init__(self, available_memory):
        self._available_memory = available_memory
        self._condition = threading.Condition()
        self._active = False
        self._foreground_waiters = 0
        self._urgent = Counter()
        self._waiting = Counter()

    @contextmanager
    def prioritize(self, key):
        with self._condition:
            self._urgent[key] += 1
            self._condition.notify_all()
        try:
            yield
        finally:
            with self._condition:
                self._urgent[key] -= 1
                if not self._urgent[key]:
                    del self._urgent[key]
                self._condition.notify_all()

    def allows_background(self, byte_count):
        available = self._available_memory()
        limit = min(1024**3, max(32 * 1024**2, available // 4)) if available else 256 * 1024**2
        return byte_count <= limit

    @contextmanager
    def acquire(self, byte_count, speculative=False, cancelled=lambda: False, key=None):
        with self._condition:
            self._waiting[key] += 1
            if not speculative:
                self._foreground_waiters += 1
            try:
                while True:
                    urgent = key in self._urgent
                    if cancelled() or speculative and not urgent and not self.allows_background(byte_count):
                        raise CancelledError()
                    urgent_queued = any(candidate in self._urgent for candidate in self._waiting)
                    if not self._active and (not speculative or urgent or
                                            not self._foreground_waiters and not urgent_queued):
                        self._active = True
                        break
                    self._condition.wait(.05)
            finally:
                self._waiting[key] -= 1
                if not self._waiting[key]:
                    del self._waiting[key]
                if not speculative:
                    self._foreground_waiters -= 1
        try:
            yield
        finally:
            with self._condition:
                self._active = False
                self._condition.notify_all()
