"""Run write-free pixel preparation while the modal GUI continues pumping."""
from concurrent.futures import CancelledError
import threading

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QDialog, QProgressDialog

from labelimg.localization.runtime import tr


class _PreparationQueue:
    """Keep cancelled, non-interruptible codecs from multiplying live pixels."""

    def __init__(self):
        self._condition = threading.Condition()
        self._pending = self._active = None
        self._stopped = False
        threading.Thread(target=self._run, name='labelimg-image-prepare', daemon=True).start()

    def submit(self, job):
        with self._condition:
            if self._pending is not None:
                self._pending[1].set()
                self._pending[2].set()
            self._pending = job
            self._condition.notify()

    def cancel(self, job):
        with self._condition:
            job[1].set()
            if self._pending is job:
                self._pending = None
                job[2].set()

    def shutdown(self, _object=None):
        with self._condition:
            self._stopped = True
            for job in (self._active, self._pending):
                if job is not None:
                    job[1].set()
                    job[2].set()
            self._pending = None
            self._condition.notify()

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._stopped or self._pending is not None)
                if self._stopped:
                    return
                self._active = job = self._pending
                self._pending = None
            job[0]()
            with self._condition:
                self._active = None


def run_preparation(work, parent):
    cancelled, completed = threading.Event(), threading.Event()
    outcome = {}

    def run():
        try:
            if cancelled.is_set():
                raise CancelledError()
            outcome['result'] = work(cancelled.is_set)
        except Exception as error:
            outcome['error'] = error
        finally:
            completed.set()

    dialog = QProgressDialog(tr('imageTools.status.processing'),
                             tr('standard.cancel'), 0, 0, parent)
    dialog.setWindowTitle(tr('imageTools.status.processing'))
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.canceled.connect(cancelled.set)
    timer = QTimer(dialog)
    timer.setInterval(10)

    def poll():
        if completed.is_set():
            dialog.done(QDialog.Accepted)
        elif dialog.wasCanceled():
            cancelled.set()
            dialog.done(QDialog.Rejected)

    timer.timeout.connect(poll)
    queue = getattr(parent, '_image_preparation_queue', None)
    if queue is None:
        queue = _PreparationQueue()
        parent._image_preparation_queue = queue
        parent.destroyed.connect(queue.shutdown)
    job = (run, cancelled, completed)
    queue.submit(job)
    timer.start()
    try:
        dialog.exec_()
    finally:
        timer.stop()
        dialog.deleteLater()
    if cancelled.is_set() or not completed.is_set():
        queue.cancel(job)
        raise CancelledError()
    if 'error' in outcome:
        raise outcome['error']
    return outcome['result']
