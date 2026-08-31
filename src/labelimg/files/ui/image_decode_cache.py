"""Bounded decoded-image cache with adjacent-image prefetch."""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import os
import threading

from PyQt5.QtGui import QImage, QImageReader


DEFAULT_DECODE_CACHE_BYTES = 256 * 1024 * 1024


class DecodedImageCache:
    """Hide source-token validation, memory bounds, and decode concurrency."""

    def __init__(self, max_bytes=DEFAULT_DECODE_CACHE_BYTES, workers=2):
        self._max_bytes = max(1, int(max_bytes))
        self._lock = threading.RLock()
        self._entries = OrderedDict()
        self._entry_bytes = 0
        self._jobs = {}
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
                return None
            self._entries.move_to_end(key)
            return QImage(image)

    def put(self, path, image):
        if not isinstance(image, QImage) or image.isNull():
            return False
        token = _source_token(path)
        if token is None:
            return False
        self._store(_path_key(path), token, image)
        return True

    def prefetch(self, paths):
        for path in tuple(dict.fromkeys(
            os.path.abspath(os.fspath(path))
            for path in paths
            if path
        )):
            key = _path_key(path)
            token = _source_token(path)
            if token is None:
                continue
            with self._lock:
                if self._shutdown:
                    return
                entry = self._entries.get(key)
                if entry is not None and entry[0] == token:
                    continue
                if key in self._jobs:
                    continue
                future = self._executor.submit(_decode_image, path, token)
                self._jobs[key] = future
            future.add_done_callback(self._prefetch_finished)

    def invalidate(self, paths):
        with self._lock:
            for path in paths:
                key = _path_key(path)
                entry = self._entries.pop(key, None)
                if entry is not None:
                    self._entry_bytes -= entry[2]

    def shutdown(self):
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._entries.clear()
            self._entry_bytes = 0
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _prefetch_finished(self, future):
        try:
            key, token, image = future.result()
        except Exception:
            return
        finally:
            with self._lock:
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
        if image.isNull() or _source_token(key) != token:
            return
        self._store(key, token, image)

    def _store(self, key, token, image):
        stored = QImage(image)
        size = _image_bytes(stored)
        with self._lock:
            if self._shutdown:
                return
            prior = self._entries.pop(key, None)
            if prior is not None:
                self._entry_bytes -= prior[2]
            self._entries[key] = (token, stored, size)
            self._entry_bytes += size
            while self._entry_bytes > self._max_bytes and self._entries:
                _old_key, old_entry = self._entries.popitem(last=False)
                self._entry_bytes -= old_entry[2]


def _decode_image(path, token):
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    return _path_key(path), token, reader.read()


def _source_token(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns


def _path_key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _image_bytes(image):
    size_in_bytes = getattr(image, "sizeInBytes", None)
    return int(size_in_bytes() if size_in_bytes is not None else image.byteCount())
