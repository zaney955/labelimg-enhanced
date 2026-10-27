"""Disposable lossless display pixels; never an annotation or source-file store."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
import zlib

from PyQt5.QtGui import QImage


_MAGIC = b'LIPREV01'
_MAX_PIXELS = 16 * 1024**2
_LOCKS = tuple(threading.Lock() for _ in range(64))
_CLEANUP_LOCK = threading.Lock()


def default_preview_directory():
    override = os.environ.get('LABELIMG_PREVIEW_CACHE_DIR')
    if override:
        return Path(override)
    config = os.environ.get('LABELIMG_CONFIG_DIR')
    if config:
        return Path(config) / 'preview-cache-v1'
    base = Path(os.environ.get('LOCALAPPDATA', os.environ.get(
        'XDG_CACHE_HOME', str(Path.home() / '.cache'))))
    return base / 'LabelImg' / 'preview-cache-v1'


class PreviewDiskCache:
    def __init__(self, directory=None, max_bytes=2 * 1024**3, max_entries=4096):
        self.directory = Path(directory) if directory is not None else default_preview_directory()
        self.max_bytes = max(0, max_bytes)
        self.max_entries = max(0, max_entries)

    def key(self, digest, size):
        return hashlib.sha256(f'rgba-v1:{digest}:{size.width()}:{size.height()}'.encode()).hexdigest()

    def _hint_path(self, path, token, size):
        identity = (os.path.normcase(os.path.abspath(path)), token, size.width(), size.height())
        name = hashlib.sha256(repr(identity).encode('utf8')).hexdigest()
        return self.directory / (name + '.hint')

    def prepared_hint(self, path, token, size):
        """Skip redundant background work only; NEVER authorize pixel display."""
        try:
            hint = self._hint_path(path, token, size)
            if hint.stat().st_size != 64:
                return False
            key = hint.read_text(encoding='ascii')
            return (all(c in '0123456789abcdef' for c in key)
                    and (self.directory / (key + '.preview')).is_file())
        except (OSError, UnicodeError):
            return False

    def remember_hint(self, path, token, size, key):
        try:
            hint = self._hint_path(path, token, size)
            if (hint.is_file() and hint.stat().st_size == 64 and hint.read_text(encoding='ascii') == key
                    or not (self.directory / (key + '.preview')).is_file()):
                return
            # A torn hint only causes extra preparation. Readers require exactly
            # 64 hex bytes and the corresponding atomically published preview.
            hint.write_text(key, encoding='ascii')
            self.prune()
        except (OSError, UnicodeError):
            pass

    @contextmanager
    def single_flight(self, key, cancelled):
        # Share across windows/cache instances, with bounded bookkeeping.
        lock = _LOCKS[int(key[:8], 16) % len(_LOCKS)]
        while not lock.acquire(timeout=.05):
            if cancelled():
                from concurrent.futures import CancelledError
                raise CancelledError()
        try:
            yield
        finally:
            lock.release()

    def load(self, key, size):
        path = self.directory / (key + '.preview')
        expected = size.width() * size.height() * 4
        if expected <= 0 or expected > _MAX_PIXELS * 4:
            return None
        try:
            if path.stat().st_size > expected + 1024**2:
                return None
            data = path.read_bytes()
            if data[:8] != _MAGIC or struct.unpack('>II', data[8:16]) != (size.width(), size.height()):
                return None
            decoder = zlib.decompressobj()
            pixels = decoder.decompress(data[16:], expected + 1)
            if len(pixels) != expected or not decoder.eof or decoder.unused_data:
                return None
            image = QImage(pixels, size.width(), size.height(), size.width() * 4,
                           QImage.Format_RGBA8888).copy()
            try:
                os.utime(path, None)
            except OSError:
                pass
            return image
        except (OSError, ValueError, struct.error, zlib.error):
            return None

    def store(self, key, image):
        if image.isNull() or image.width() * image.height() > _MAX_PIXELS:
            return
        temporary = None
        try:
            rgba = image.convertToFormat(QImage.Format_RGBA8888)
            pixels = rgba.constBits().asstring(rgba.sizeInBytes())
            data = _MAGIC + struct.pack('>II', rgba.width(), rgba.height()) + zlib.compress(pixels, 1)
            if len(data) > self.max_bytes or not self.max_entries:
                return
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix='.preview-', suffix='.tmp',
                                             delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
            os.replace(temporary, self.directory / (key + '.preview'))
            self.prune()
        except OSError:
            pass  # Cache permissions/disk space must never block image access.
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def prune(self, *, clear=False):
        """Bound LRU disk use; clear only this cache's recognized entries."""
        with _CLEANUP_LOCK:
            try:
                entries = []
                for temporary in self.directory.glob('.preview-*.tmp'):
                    try:
                        if time.time() - temporary.stat().st_mtime > 86400:
                            temporary.unlink(missing_ok=True)
                    except OSError:
                        pass
                for path in self.directory.iterdir():
                    if path.suffix not in ('.preview', '.hint'):
                        continue
                    if len(path.stem) != 64 or any(c not in '0123456789abcdef' for c in path.stem):
                        continue
                    try:
                        stat = path.stat()
                        entries.append((stat.st_mtime_ns, stat.st_size, path))
                    except OSError:
                        continue
                total, count = sum(row[1] for row in entries), len(entries)
                for _time, size, path in sorted(entries):
                    if not clear and total <= self.max_bytes and count <= self.max_entries:
                        break
                    try:
                        path.unlink(missing_ok=True)
                        total -= size
                        count -= 1
                    except OSError:
                        continue
            except OSError:
                pass
