"""Bounded decoded-image cache with adjacent-image prefetch."""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import CancelledError, ThreadPoolExecutor
import os
import threading
import time

from PyQt5.QtGui import QImage, QImageReader


DEFAULT_DECODE_CACHE_BYTES = 256 * 1024 * 1024
MAX_DECODE_CACHE_BYTES = 1024 * 1024 * 1024


def _available_memory_bytes():
    try:
        if os.name == 'nt':
            import ctypes
            class MemoryStatus(ctypes.Structure):
                _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                    (name, ctypes.c_ulonglong) for name in (
                        'total_physical', 'available_physical', 'total_page',
                        'available_page', 'total_virtual', 'available_virtual', 'extended')]
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.available_physical
        else:
            return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    except (AttributeError, OSError, ValueError):
        pass
    return None


def _default_cache_budget():
    available = _available_memory_bytes()
    if available is None or available <= 0:
        return DEFAULT_DECODE_CACHE_BYTES
    return min(MAX_DECODE_CACHE_BYTES, max(32 * 1024 * 1024, available // 8))


class DecodedImageCache:
    """Hide source-token validation, memory bounds, and decode concurrency."""

    def __init__(self, max_bytes=None, workers=2, *, fingerprint_for=None,
                 verification_interval=2.0):
        self._max_bytes = max(1, int(_default_cache_budget() if max_bytes is None else max_bytes))
        self._lock = threading.RLock()
        self._entries = OrderedDict()
        self._entry_bytes = 0
        self._jobs = {}
        self._wanted = set()
        self._fingerprint_for = fingerprint_for
        self._fingerprints = OrderedDict()
        self._verification_jobs = {}
        self._verified_at = {}
        self._verification_interval = verification_interval
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(workers)),
            thread_name_prefix="labelimg-prefetch",
        )
        self._shutdown = False

    def get(self, path):
        key = _path_key(path)
        token = _source_token(path)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            cached_token, image, size = entry
            if token is None or token != cached_token:
                self._entries.pop(key, None)
                self._entry_bytes -= size
                self._fingerprints.pop(key, None)
                return None
            self._entries.move_to_end(key)
            self._verify_in_background(key, token, image)
            return QImage(image)

    def put(self, path, image):
        if not isinstance(image, QImage) or image.isNull():
            return False
        token = _source_token(path)
        if token is None:
            return False
        with self._lock:
            known = self._fingerprints.get(_path_key(path))
            if known is not None and known[1] == image.cacheKey() and known[0] != token:
                return False  # These pixels were decoded from an older source.
        self._store(_path_key(path), token, image)
        return True

    def load(self, path):
        """Blocking decode for a worker; reuse any already running prefetch."""
        image = self.get(path)
        if image is not None:
            return image
        key, token = _path_key(path), _source_token(path)
        with self._lock:
            future = self._jobs.get(key)
            if future is None:
                # A prefetch may have finished between the optimistic cache
                # lookup above and this job lookup. Recheck while holding the
                # same lock used to store the completed decode.
                image = self.get(path)
                if image is not None:
                    return image
        if future is not None and not future.cancelled():
            try:
                _key, job_token, image, fingerprint = future.result()
                if job_token == token and _source_token(path) == token:
                    self._store(key, token, image, fingerprint)
                    return QImage(image)
            except CancelledError:
                pass  # Prefetch priority changed while demand was taking over.
        _key, decoded_token, image, fingerprint = _decode_image(path, token, self._fingerprint_for)
        if _source_token(path) != decoded_token:
            raise OSError('image changed while it was being decoded')
        self._store(key, token, image, fingerprint)
        return image

    def cached_fingerprint(self, path, image):
        key, token = _path_key(path), _source_token(path)
        with self._lock:
            entry = self._fingerprints.get(key)
            if entry is not None and entry[:2] == (token, image.cacheKey()):
                self._fingerprints.move_to_end(key)
                return entry[2]
        return None

    def prepare_fingerprint(self, path, image):
        """Bind a fingerprint to these pixels; call off-thread for large images."""
        cached = self.cached_fingerprint(path, image)
        if cached is not None or self._fingerprint_for is None:
            return cached
        token = _source_token(path)
        with self._lock:
            known = self._fingerprints.get(_path_key(path))
            if known is not None and known[1] == image.cacheKey() and known[0] != token:
                raise OSError('decoded pixels belong to an older image source')
        fingerprint = self._fingerprint_for(path, (image.width(), image.height()))
        if token is None or token != _source_token(path):
            raise OSError('image changed while its fingerprint was being prepared')
        with self._lock:
            if not self._shutdown:
                self._remember_fingerprint(_path_key(path), token, image, fingerprint)
        return fingerprint

    def prefetch(self, paths, *, current_path=None):
        paths = tuple(dict.fromkeys(
            os.path.abspath(os.fspath(path))
            for path in paths
            if path
        ))
        wanted = {_path_key(path) for path in paths}
        with self._lock:
            self._wanted = wanted
            verification_targets = wanted | ({_path_key(current_path)} if current_path else set())
            for key, future in tuple(self._verification_jobs.items()):
                if key not in verification_targets:
                    future.cancel()
            for key, future in tuple(self._jobs.items()):
                if key not in wanted:
                    future.cancel()
        for path in paths:
            key = _path_key(path)
            token = _source_token(path)
            if token is None:
                continue
            # An oversized decode cannot enter this LRU. Prefetching it only
            # wastes CPU and multiplies peak memory while the user navigates.
            size = QImageReader(path).size()
            if size.width() * size.height() * 4 > self._max_bytes // 2:
                continue
            with self._lock:
                if self._shutdown:
                    return
                entry = self._entries.get(key)
                if entry is not None and entry[0] == token:
                    continue
                if key in self._jobs:
                    continue
                future = self._executor.submit(_decode_image, path, token, self._fingerprint_for)
                self._jobs[key] = future
            future.add_done_callback(self._prefetch_finished)

    def invalidate(self, paths):
        with self._lock:
            for path in paths:
                key = _path_key(path)
                entry = self._entries.pop(key, None)
                if entry is not None:
                    self._entry_bytes -= entry[2]
                self._fingerprints.pop(key, None)
                self._verified_at.pop(key, None)

    def shutdown(self):
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._entries.clear()
            self._fingerprints.clear()
            self._verified_at.clear()
            self._entry_bytes = 0
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _prefetch_finished(self, future):
        try:
            key, token, image, fingerprint = future.result()
        except Exception:
            with self._lock:
                self._remove_job(future)
            return
        with self._lock:
            if (
                not image.isNull()
                and _source_token(key) == token
                and key in self._wanted
            ):
                self._store(key, token, image, fingerprint)
            self._remove_job(future)

    def _remove_job(self, future):
        matching = next(
            (
                job_key
                for job_key, job in self._jobs.items()
                if job is future
            ),
            None,
        )
        if matching is not None:
            self._jobs.pop(matching, None)

    def _store(self, key, token, image, fingerprint=None):
        stored = QImage(image)
        size = _image_bytes(stored)
        with self._lock:
            if self._shutdown:
                return
            previous = self._fingerprints.get(key)
            if fingerprint is not None:
                self._remember_fingerprint(key, token, image, fingerprint)
            elif previous is not None and previous[:2] != (token, image.cacheKey()):
                self._fingerprints.pop(key, None)
            if size > self._max_bytes:
                return  # Keep prepared identity without evicting useful neighbors.
            prior = self._entries.pop(key, None)
            if prior is not None:
                self._entry_bytes -= prior[2]
            self._entries[key] = (token, stored, size)
            self._entry_bytes += size
            while self._entry_bytes > self._max_bytes and self._entries:
                _old_key, old_entry = self._entries.popitem(last=False)
                self._entry_bytes -= old_entry[2]

    def _remember_fingerprint(self, key, token, image, fingerprint):
        self._fingerprints[key] = (token, image.cacheKey(), fingerprint)
        self._fingerprints.move_to_end(key)
        self._verified_at[key] = time.monotonic()
        while len(self._fingerprints) > 1024:
            old_key, _entry = self._fingerprints.popitem(last=False)
            self._verified_at.pop(old_key, None)

    def _verify_in_background(self, key, token, image):
        """Check content behind unchanged metadata without blocking navigation."""
        expected = self._fingerprints.get(key)
        if (self._shutdown or self._fingerprint_for is None or expected is None
                or expected[:2] != (token, image.cacheKey())
                or key in self._verification_jobs
                or time.monotonic() - self._verified_at.get(key, 0) < self._verification_interval):
            return
        self._verified_at[key] = time.monotonic()
        future = self._executor.submit(
            self._fingerprint_for, key, (image.width(), image.height())
        )
        self._verification_jobs[key] = future
        future.add_done_callback(lambda completed: self._verification_finished(key, token, expected, completed))

    def _verification_finished(self, key, token, expected, future):
        if future.cancelled():
            with self._lock:
                self._verification_jobs.pop(key, None)
            return
        try:
            actual = future.result()
        except Exception:
            actual = None  # An unreadable source must not remain a trusted hit.
        with self._lock:
            self._verification_jobs.pop(key, None)
            if self._shutdown or self._fingerprints.get(key) != expected:
                return
            if _source_token(key) != token or actual != expected[2]:
                self.invalidate((key,))


def _decode_image(path, token, fingerprint_for=None):
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    image = reader.read()
    fingerprint = (
        fingerprint_for(path, (image.width(), image.height()))
        if fingerprint_for is not None and not image.isNull() else None
    )
    if token != _source_token(path):
        raise OSError('image changed while it was being decoded')
    return _path_key(path), token, image, fingerprint


def _source_token(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _path_key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _image_bytes(image):
    size_in_bytes = getattr(image, "sizeInBytes", None)
    return int(size_in_bytes() if size_in_bytes is not None else image.byteCount())
