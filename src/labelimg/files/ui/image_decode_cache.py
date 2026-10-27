"""Bounded decoded-image cache with adjacent-image prefetch."""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import CancelledError, ThreadPoolExecutor
import hashlib
import os
import threading
import time

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, QSize
from PyQt5.QtGui import QImage, QImageReader
from labelimg.platform.image_metadata import ImageMetadata
from labelimg.files.ui.decode_budget import DecodeBudget


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


_HEAVY_DECODES = DecodeBudget(_available_memory_bytes)


class DecodedImageCache:
    """Hide source-token validation, memory bounds, and decode concurrency."""

    def __init__(self, max_bytes=None, workers=2, *, fingerprint_for=None,
                 verification_interval=2.0, preview_size=None, disk_preview=None):
        self._max_bytes = max(1, int(_default_cache_budget() if max_bytes is None else max_bytes))
        self._lock = threading.RLock()
        self._entries = OrderedDict()
        self._entry_bytes = 0
        self._jobs = {}
        self._wanted = set()
        self._fingerprint_for = fingerprint_for
        self._fingerprints = OrderedDict()
        self._metadata = OrderedDict()
        self._prepared = OrderedDict()
        self._retired_pixels = OrderedDict()
        self.preview_size = preview_size
        self._disk_preview = disk_preview
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
                self.invalidate((key,))
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
            if image.cacheKey() in self._retired_pixels:
                return False
            prepared = self._prepared.get((_path_key(path), image.cacheKey()))
            if prepared is not None:
                if prepared[0] != token:
                    return False
                self._store(_path_key(path), token, image, prepared[1], prepared[2])
                return True
            known = self._fingerprints.get(_path_key(path))
            if known is not None and known[1] == image.cacheKey() and known[0] != token:
                return False  # These pixels were decoded from an older source.
        self._store(_path_key(path), token, image)
        return True

    def load(self, path):
        """Blocking decode for a worker; reuse any already running prefetch."""
        with _HEAVY_DECODES.prioritize(_path_key(path)):
            return self._load(path)

    def _load(self, path):
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
                _key, job_token, image, fingerprint, metadata = future.result()
                if job_token == token and _source_token(path) == token:
                    self._store(key, token, image, fingerprint, metadata)
                    return QImage(image)
            except CancelledError:
                pass  # Prefetch priority changed while demand was taking over.
        _key, decoded_token, image, fingerprint, metadata = self._decode(path, token)
        if _source_token(path) != decoded_token:
            raise OSError('image changed while it was being decoded')
        self._store(key, token, image, fingerprint, metadata)
        return image

    def _decode(self, path, token, speculative=False):
        args = (path, token, self._fingerprint_for, self.preview_size)
        if self._disk_preview is None:
            return _decode_image(*args)
        key = _path_key(path)
        return _decode_image(*args, self._disk_preview,
                             lambda: self._shutdown or speculative and key not in self._wanted,
                             speculative)

    def image_metadata(self, path, image):
        key, token = _path_key(path), _source_token(path)
        with self._lock:
            prepared = self._prepared.get((key, image.cacheKey()))
            if prepared is not None and prepared[0] == token:
                return prepared[2]
            entry = self._metadata.get(key)
            if entry is not None and entry[:2] == (token, image.cacheKey()):
                return entry[2]
        return ImageMetadata(image.width(), image.height(), _image_is_grayscale(image))

    def cached_fingerprint(self, path, image):
        key, token = _path_key(path), _source_token(path)
        with self._lock:
            if image.cacheKey() in self._retired_pixels:
                return None
            prepared = self._prepared.get((key, image.cacheKey()))
            if prepared is not None and prepared[0] == token:
                return prepared[1]
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
            if image.cacheKey() in self._retired_pixels:
                raise OSError('decoded pixels were invalidated')
            known = self._fingerprints.get(_path_key(path))
            if known is not None and known[1] == image.cacheKey() and known[0] != token:
                raise OSError('decoded pixels belong to an older image source')
        metadata = self.image_metadata(path, image)
        fingerprint = self._fingerprint_for(path, (metadata.width(), metadata.height()))
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
            reader = QImageReader(path)
            size = reader.size()
            format_name = bytes(reader.format()).lower()
            if format_name in (b'jpeg', b'jpg'):
                size = _preview_decode_size(size, self.preview_size)
            elif format_name == b'png' and self._disk_preview is not None:
                rotated = bool(int(reader.transformation()) & 4)
                bounds = tuple(reversed(self.preview_size)) if self.preview_size and rotated else self.preview_size
                preview = _preview_decode_size(size, bounds)
                required = size.width() * size.height() * 4 + token[2] * 2
                output = QSize(preview)
                if rotated:
                    output.transpose()
                disk_ready = self._disk_preview.prepared_hint(path, token, output)
                preview_bytes = preview.width() * preview.height() * 4
                if preview != size and (_HEAVY_DECODES.allows_background(required + preview_bytes)
                        or disk_ready and _HEAVY_DECODES.allows_background(token[2] * 2 + preview_bytes)):
                    size = preview
            # Release the header reader before any source mutation can run.
            del reader
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
                future = self._executor.submit(
                    self._decode, path, token, True)
                self._jobs[key] = future
            future.add_done_callback(self._prefetch_finished)

    def invalidate(self, paths):
        with self._lock:
            for path in paths:
                key = _path_key(path)
                for pixel_key in tuple(self._prepared):
                    if pixel_key[0] == key:
                        self._retired_pixels[pixel_key[1]] = None
                        self._prepared.pop(pixel_key, None)
                known = self._fingerprints.get(key) or self._metadata.get(key)
                if known is not None:
                    self._retired_pixels[known[1]] = None
                    while len(self._retired_pixels) > 1024:
                        self._retired_pixels.popitem(last=False)
                entry = self._entries.pop(key, None)
                if entry is not None:
                    self._entry_bytes -= entry[2]
                self._fingerprints.pop(key, None)
                self._metadata.pop(key, None)
                self._verified_at.pop(key, None)

    def shutdown(self):
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._entries.clear()
            self._fingerprints.clear()
            self._metadata.clear()
            self._prepared.clear()
            self._retired_pixels.clear()
            self._verified_at.clear()
            self._entry_bytes = 0
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _prefetch_finished(self, future):
        try:
            key, token, image, fingerprint, metadata = future.result()
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
                self._store(key, token, image, fingerprint, metadata)
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

    def _store(self, key, token, image, fingerprint=None, metadata=None):
        stored = QImage(image)
        size = _image_bytes(stored)
        with self._lock:
            if self._shutdown or image.cacheKey() in self._retired_pixels:
                return
            if metadata is not None:
                # A second decode/size of the same source may finish while the
                # first result is waiting for UI publication. Retain its own
                # identity rather than inheriting the newest pixel buffer's.
                for pixel_key, value in tuple(self._prepared.items()):
                    if pixel_key[0] == key and (value[0] != token or value[1] != fingerprint):
                        self._retired_pixels[pixel_key[1]] = None
                        self._prepared.pop(pixel_key, None)
                pixel_key = (key, image.cacheKey())
                self._prepared[pixel_key] = (token, fingerprint, metadata)
                self._prepared.move_to_end(pixel_key)
                while len(self._prepared) > 1024:
                    self._prepared.popitem(last=False)
                while len(self._retired_pixels) > 1024:
                    self._retired_pixels.popitem(last=False)
            known_metadata = self._metadata.get(key)
            if metadata is not None:
                self._metadata[key] = (token, image.cacheKey(), metadata)
                self._metadata.move_to_end(key)
                while len(self._metadata) > 1024:
                    self._metadata.popitem(last=False)
            elif known_metadata is not None and known_metadata[:2] != (token, image.cacheKey()):
                self._metadata.pop(key, None)
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
        pixel_key = (key, image.cacheKey())
        prepared = self._prepared.get(pixel_key)
        if prepared is not None and prepared[0] == token:
            self._prepared[pixel_key] = (token, fingerprint, prepared[2])
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
            self._fingerprint_for, key, expected[2].dimensions
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


def _preview_decode_size(size, bounds):
    """Choose a native JPEG reduction that still covers the fitted viewport."""
    if not bounds or size.width() * size.height() <= 4_000_000:
        return size
    ratio = min(bounds[0] / max(1, size.width()), bounds[1] / max(1, size.height()))
    divisor = next((value for value in (8, 4, 2) if ratio <= 1 / value), 1)
    return QSize((size.width() + divisor - 1) // divisor,
                 (size.height() + divisor - 1) // divisor)


def _read_source_pixels(reader):
    return reader.read()


def _decode_image(path, token, fingerprint_for=None, preview_size=None,
                  disk_preview=None, cancelled=lambda: False, speculative=False):
    # Decode a detached byte snapshot: Windows must not keep the original file
    # locked throughout a long decode/refinement. Its digest also proves that
    # prepared pixels and the published fingerprint describe the same bytes.
    content = QByteArray()
    content.reserve(os.path.getsize(path))
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            if cancelled():
                raise CancelledError()
            content.append(chunk)
            digest.update(chunk)
    buffer = QBuffer()
    buffer.setData(content)
    buffer.open(QIODevice.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    source_size = reader.size()
    rotated = bool(int(reader.transformation()) & 4)
    bounds = tuple(reversed(preview_size)) if preview_size and rotated else preview_size
    decode_size = _preview_decode_size(source_size, bounds)
    if decode_size != source_size:
        reader.setScaledSize(decode_size)
    output_size = QSize(decode_size)
    if rotated:
        output_size.transpose()
    format_name = bytes(reader.format()).lower()
    use_disk = disk_preview is not None and format_name == b'png' and decode_size != source_size

    def decode():
        heavy = (source_size.width() * source_size.height() > 4_000_000
                 and (format_name not in (b'jpeg', b'jpg') or decode_size == source_size))
        if heavy:
            required = source_size.width() * source_size.height() * 4 + len(content) * 2
            if decode_size != source_size:
                required += decode_size.width() * decode_size.height() * 4
            with _HEAVY_DECODES.acquire(required, speculative, cancelled, _path_key(path)):
                return _read_source_pixels(reader)
        if cancelled():
            raise CancelledError()
        return _read_source_pixels(reader)

    if use_disk:
        key = disk_preview.key(digest.hexdigest(), output_size)
        image = disk_preview.load(key, output_size)
        if image is None:
            with disk_preview.single_flight(key, cancelled):
                image = disk_preview.load(key, output_size)
                if image is None:
                    image = decode().convertToFormat(QImage.Format_RGBA8888)
                    if not cancelled() and token == _source_token(path):
                        disk_preview.store(key, image)
        if not cancelled() and token == _source_token(path):
            disk_preview.remember_hint(path, token, output_size, key)
    else:
        image = decode()
    if rotated:
        source_size.transpose()
    metadata = (ImageMetadata(source_size.width(), source_size.height(), _image_is_grayscale(image))
                if not image.isNull() else None)
    fingerprint = (
        fingerprint_for(path, (metadata.width(), metadata.height()))
        if fingerprint_for is not None and not image.isNull() else None
    )
    if token != _source_token(path):
        raise OSError('image changed while it was being decoded')
    if fingerprint is not None and fingerprint.sha256 != digest.hexdigest():
        raise OSError('decoded pixels do not match the current image content')
    return _path_key(path), token, image, fingerprint, metadata


def _image_is_grayscale(image):
    # Qt's RGB allGray scan holds the GIL for a whole enormous frame. Compare
    # bounded views instead so a finishing full decode cannot freeze navigation.
    if (image.width() * image.height() <= 4_000_000
            or image.format() not in (QImage.Format_RGB32, QImage.Format_ARGB32,
                                      QImage.Format_ARGB32_Premultiplied)):
        return image.isGrayscale()
    tile_height = max(1, (1024 * 1024) // image.bytesPerLine())
    for top in range(0, image.height(), tile_height):
        if not image.copy(0, top, image.width(), min(tile_height, image.height() - top)).isGrayscale():
            return False
    return True


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
