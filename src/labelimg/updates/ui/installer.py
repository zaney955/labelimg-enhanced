"""Asynchronous download and integrity verification for an update installer."""

from pathlib import Path

from PyQt5.QtCore import QDir, QObject, QTemporaryDir, QTimer, QUrl, pyqtSignal
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from labelimg.localization.runtime import tr
from labelimg.updates.infrastructure import (
    MAX_INSTALLER_BYTES,
    MAX_SHA256_MANIFEST_BYTES,
    installer_asset_name,
    parse_sha256_manifest,
    sha256_matches,
)


class InstallerDownloadClient(QObject):
    progress = pyqtSignal(int, int)
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, app_version, parent=None, manager=None):
        super().__init__(parent)
        self.app_version = str(app_version)
        self.manager = manager or QNetworkAccessManager(self)
        self._reply = None
        self._kind = None
        self._release = None
        self._manifest = bytearray()
        self._expected_digest = None
        self._stream = None
        self._temporary = None
        self._candidate = None
        self._ready = False
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(120000)
        self._timeout.timeout.connect(self._abort_timed_out_reply)

    def download(self, release):
        if self._reply is not None or self._ready:
            return False
        if not release.installer_url or not release.sha256_url:
            self.failed.emit(tr("updates.install.missingAssets"))
            return False
        self._release = release
        self._temporary = QTemporaryDir(
            QDir.tempPath() + "/labelimg-update-XXXXXX"
        )
        if not self._temporary.isValid():
            self._fail(tr("updates.install.tempFailed"))
            return False
        self._candidate = str(
            Path(self._temporary.path())
            / installer_asset_name(release.version)
        )
        return self._start_request(release.sha256_url, "manifest")

    def cancel(self):
        reply = self._reply
        self._reply = None
        self._kind = None
        self._timeout.stop()
        self._close_stream()
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        if not self._ready:
            self._discard_candidate()

    def take_candidate(self):
        if not self._ready or self._temporary is None:
            return None
        self._temporary.setAutoRemove(False)
        return self._candidate

    @property
    def candidate_path(self):
        return self._candidate if self._ready else None

    def _start_request(self, url, kind):
        request = QNetworkRequest(QUrl(str(url)))
        request.setRawHeader(
            b"User-Agent",
            ("LabelImg-Enhanced/%s" % self.app_version).encode("ascii"),
        )
        request.setRawHeader(
            b"Accept",
            b"text/plain" if kind == "manifest" else b"application/octet-stream",
        )
        request.setAttribute(
            QNetworkRequest.RedirectPolicyAttribute,
            QNetworkRequest.NoLessSafeRedirectPolicy,
        )
        self._reply = self.manager.get(request)
        self._kind = kind
        self._reply.readyRead.connect(self._read_available)
        self._reply.downloadProgress.connect(self._download_progress)
        self._reply.finished.connect(self._finish)
        self._timeout.start()
        return True

    def _read_available(self):
        reply = self._reply
        if reply is None:
            return
        self._timeout.start()
        chunk = bytes(reply.readAll())
        if self._kind == "manifest":
            self._manifest.extend(chunk)
            if len(self._manifest) > MAX_SHA256_MANIFEST_BYTES:
                reply.setProperty("labelimgUpdateTooLarge", True)
                reply.abort()
        elif self._kind == "installer" and self._stream is not None:
            self._stream.write(chunk)
            if self._stream.tell() > MAX_INSTALLER_BYTES:
                reply.setProperty("labelimgUpdateTooLarge", True)
                reply.abort()

    def _download_progress(self, received, total):
        if self._kind != "installer":
            return
        if max(int(received), int(total)) > MAX_INSTALLER_BYTES:
            self._reply.setProperty("labelimgUpdateTooLarge", True)
            self._reply.abort()
            return
        self.progress.emit(int(received), int(total))

    def _finish(self):
        reply = self._reply
        kind = self._kind
        self._read_available()
        self._reply = None
        self._kind = None
        self._timeout.stop()
        if reply is None:
            return
        try:
            if reply.property("labelimgUpdateTimedOut"):
                self._fail(tr("updates.error.timeout"))
                return
            if reply.property("labelimgUpdateTooLarge"):
                self._fail(tr("updates.install.tooLarge"))
                return
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            status = int(status) if status is not None else 0
            if reply.error() != QNetworkReply.NoError:
                self._fail(reply.errorString())
                return
            if status != 200:
                self._fail(tr("updates.error.http", status=status))
                return
            if kind == "manifest":
                self._finish_manifest()
            else:
                self._finish_installer()
        finally:
            reply.deleteLater()

    def _finish_manifest(self):
        try:
            manifest = self._manifest.decode("utf-8", errors="strict")
            self._expected_digest = parse_sha256_manifest(
                manifest,
                installer_asset_name(self._release.version),
            )
            self._stream = Path(self._candidate).open("xb")
        except (OSError, UnicodeError, ValueError) as error:
            self._fail(str(error))
            return
        self._start_request(self._release.installer_url, "installer")

    def _finish_installer(self):
        self._close_stream()
        try:
            verified = sha256_matches(
                self._candidate,
                self._expected_digest,
            )
        except OSError as error:
            self._fail(str(error))
            return
        if not verified:
            self._fail(tr("updates.install.hashMismatch"))
            return
        self._ready = True
        self.succeeded.emit(self._candidate)

    def _abort_timed_out_reply(self):
        if self._reply is not None:
            self._reply.setProperty("labelimgUpdateTimedOut", True)
            self._reply.abort()

    def _fail(self, detail):
        self._close_stream()
        self._discard_candidate()
        self.failed.emit(str(detail))

    def _close_stream(self):
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def _discard_candidate(self):
        self._ready = False
        self._candidate = None
        self._temporary = None
