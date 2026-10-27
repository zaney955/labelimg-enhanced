"""Cancelable, single-worker preparation of PNG previews in the open directory."""
import threading
from PyQt5.QtCore import QSize
from PyQt5.QtGui import QImageReader
from labelimg.files.ui.image_decode_cache import _decode_image, _preview_decode_size, _source_token


class PreviewWarmup:
    def __init__(self, disk):
        self._disk = disk
        self._condition = threading.Condition()
        self._generation = 0
        self._pending = None
        self._active = False
        self._stopped = False
        self._thread = None

    def submit(self, paths, bounds):
        with self._condition:
            if self._stopped:
                return
            self._generation += 1
            self._pending = (self._generation, tuple(paths), bounds)
            if self._thread is None and not self._stopped:
                self._thread = threading.Thread(target=self._run, name='labelimg-png-previews', daemon=True)
                self._thread.start()
            self._condition.notify_all()

    def shutdown(self):
        with self._condition:
            self._stopped = True
            self._generation += 1
            self._pending = None
            self._condition.notify_all()

    def join(self):
        if self._thread is not None:
            self._thread.join(timeout=5)

    def wait(self, timeout):
        with self._condition:
            return self._condition.wait_for(lambda: not self._active and self._pending is None, timeout)

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._stopped or self._pending is not None)
                if self._stopped:
                    return
                generation, paths, bounds = self._pending
                self._pending = None
                self._active = True
            self._disk.prune()
            cancelled = lambda: self._stopped or generation != self._generation
            for path in paths:
                if cancelled():
                    break
                try:
                    reader = QImageReader(path)
                    size, format_name = reader.size(), bytes(reader.format()).lower()
                    rotated = bool(int(reader.transformation()) & 4)
                    del reader
                    adjusted = tuple(reversed(bounds)) if bounds and rotated else bounds
                    preview = _preview_decode_size(size, adjusted)
                    if format_name != b'png' or preview == size:
                        continue
                    output = QSize(preview)
                    if rotated:
                        output.transpose()
                    token = _source_token(path)
                    if self._disk.prepared_hint(path, token, output):
                        continue
                    _decode_image(path, token, None, bounds, self._disk, cancelled, True)
                except Exception:
                    continue  # Missing/oversized/unreadable entries do not stop the directory.
            with self._condition:
                self._active = False
                self._condition.notify_all()
