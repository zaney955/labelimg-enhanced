"""One active decode plus one replaceable destination; no key-repeat backlog."""
import threading

from PyQt5.QtCore import QEvent, QObject, pyqtSignal
from PyQt5.QtGui import QImage
from labelimg.files.ui.image_decode_cache import _source_token


class NavigationLoader(QObject):
    completed = pyqtSignal(int, str, object, object)

    def __init__(self, cache, parent):
        super().__init__(parent)
        self._cache = cache
        self._condition = threading.Condition()
        self._pending = None
        self._active = False
        self._stopped = False
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name='labelimg-navigation')
        parent.destroyed.connect(self.shutdown)
        parent.installEventFilter(self)
        self._thread.start()

    def eventFilter(self, watched, event):
        if watched is self.parent() and event.type() == QEvent.DeferredDelete:
            self.shutdown()
        return super().eventFilter(watched, event)

    @property
    def busy(self):
        with self._condition:
            return self._active or self._pending is not None

    def submit(self, generation, path, expected=None):
        with self._condition:
            self._pending = (generation, path, expected)
            self._condition.notify()

    def cancel(self):
        with self._condition:
            self._pending = None

    def shutdown(self, _object=None):
        with self._condition:
            self._stopped = True
            self._pending = None
            self._condition.notify()

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._stopped or self._pending is not None)
                if self._stopped:
                    return
                generation, path, expected = self._pending
                self._pending = None
                self._active = True
            try:
                token = _source_token(path)
                image = (self._cache.load(path) if expected is None
                         else self._cache.load_full(path, expected))
            except Exception:
                image = QImage()
            with self._condition:
                self._active = False
                if self._stopped:
                    return
                # Do not retain stale large QImages in the Qt event queue.
                if self._pending is None:
                    self.completed.emit(generation, path, image, token)
