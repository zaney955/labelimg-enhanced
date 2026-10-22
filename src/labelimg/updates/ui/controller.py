"""Asynchronous Qt coordination for checking and presenting updates."""

import time

from PyQt5 import sip

from PyQt5.QtCore import QObject, QProcess, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt5.QtWidgets import QApplication

from labelimg.localization.runtime import tr
from labelimg.platform.settings_keys import (
    SETTING_AUTO_CHECK_UPDATES,
    SETTING_UPDATE_CACHED_RELEASE,
    SETTING_UPDATE_FAILURE_COUNT,
    SETTING_UPDATE_IGNORED_VERSION,
    SETTING_UPDATE_LAST_CHECKED_AT,
    SETTING_UPDATE_NEXT_CHECK_AT,
    SETTING_UPDATE_SNOOZED_UNTIL,
)
from labelimg.updates.application import (
    CHECK_INTERVAL_SECONDS,
    SNOOZE_SECONDS,
    automatic_check_due,
    evaluate_update,
    next_automatic_check_at,
)
from labelimg.updates.domain import UpdateDecisionKind
from labelimg.updates.infrastructure import (
    GITHUB_LATEST_RELEASE_WEB_URL,
    MAX_RELEASE_RESPONSE_BYTES,
    build_web_request_headers,
    release_from_latest_redirect,
    detect_distribution_strategy,
)
from .installer import InstallerDownloadClient
from .notification import UpdateCenterWindow


class GitHubReleaseClient(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    _TRANSIENT_ERRORS = {
        QNetworkReply.RemoteHostClosedError,
        QNetworkReply.TimeoutError,
        QNetworkReply.TemporaryNetworkFailureError,
        QNetworkReply.NetworkSessionFailedError,
        QNetworkReply.ProxyConnectionClosedError,
        QNetworkReply.ProxyTimeoutError,
        QNetworkReply.UnknownNetworkError,
        QNetworkReply.UnknownProxyError,
    }

    def __init__(
        self,
        app_version,
        parent=None,
        manager=None,
        retry_delays_ms=(250, 1000),
    ):
        super().__init__(parent)
        self.app_version = str(app_version)
        self.manager = manager or QNetworkAccessManager(self)
        self._reply = None
        self._request_kind = None
        self._retry_delays_ms = tuple(int(value) for value in retry_delays_ms)
        self._retry_attempt = 0
        self._retry_request = None
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._start_retry)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(10000)
        self._timeout.timeout.connect(self._abort_timed_out_reply)

    def fetch(self):
        if self._reply is not None or self._retry_timer.isActive():
            return False
        self._retry_attempt = 0
        self._retry_request = None
        return self._start_request(
            GITHUB_LATEST_RELEASE_WEB_URL,
            build_web_request_headers(self.app_version),
            "web",
        )

    def _start_request(self, url, headers, kind):
        self._retry_request = (str(url), dict(headers), kind)
        request = QNetworkRequest(QUrl(url))
        for name, value in headers.items():
            request.setRawHeader(name.encode("ascii"), value.encode("ascii"))
        if hasattr(request, "setTransferTimeout"):
            request.setTransferTimeout(10000)
        request.setAttribute(
            QNetworkRequest.RedirectPolicyAttribute,
            QNetworkRequest.ManualRedirectPolicy,
        )
        self._reply = self.manager.get(request)
        self._request_kind = kind
        self._reply.finished.connect(self._finish)
        self._reply.downloadProgress.connect(self._check_response_size)
        self._timeout.start()
        return True

    def cancel(self):
        reply = self._reply
        self._reply = None
        self._request_kind = None
        self._retry_request = None
        self._retry_timer.stop()
        self._timeout.stop()
        if reply is not None:
            reply.abort()
            reply.deleteLater()

    def _abort_timed_out_reply(self):
        if self._reply is not None:
            self._reply.setProperty("labelimgUpdateTimedOut", True)
            self._reply.abort()

    def _check_response_size(self, received, total):
        reply = self._reply
        if (
            reply is not None
            and max(int(received), int(total)) > MAX_RELEASE_RESPONSE_BYTES
        ):
            reply.setProperty("labelimgUpdateTooLarge", True)
            reply.abort()

    def _start_retry(self):
        request = self._retry_request
        if request is None or self._reply is not None:
            return
        self._start_request(*request)

    def _retry_transient_failure(self, reply):
        if reply.error() not in self._TRANSIENT_ERRORS:
            return False
        if self._retry_attempt >= len(self._retry_delays_ms):
            return False
        delay = self._retry_delays_ms[self._retry_attempt]
        self._retry_attempt += 1
        self._retry_timer.start(max(0, delay))
        return True

    def _reset_retry(self):
        self._retry_attempt = 0
        self._retry_request = None
        self._retry_timer.stop()

    def _finish(self):
        reply = self._reply
        request_kind = self._request_kind
        self._reply = None
        self._request_kind = None
        self._timeout.stop()
        if reply is None:
            return
        try:
            if reply.property("labelimgUpdateTooLarge"):
                self._reset_retry()
                self.failed.emit(tr("updates.error.tooLarge"))
                return
            if reply.property("labelimgUpdateTimedOut"):
                if self._retry_attempt < len(self._retry_delays_ms):
                    delay = self._retry_delays_ms[self._retry_attempt]
                    self._retry_attempt += 1
                    self._retry_timer.start(max(0, delay))
                    return
                self._reset_retry()
                self.failed.emit(tr("updates.error.timeout"))
                return
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            status = int(status) if status is not None else 0
            if request_kind == "web" and status in (
                200, 301, 302, 303, 307, 308
            ):
                target = reply.attribute(
                    QNetworkRequest.RedirectionTargetAttribute
                )
                release_url = (
                    reply.url().resolved(target).toString()
                    if target is not None
                    else reply.url().toString()
                )
                try:
                    release = release_from_latest_redirect(release_url)
                except ValueError as error:
                    self._reset_retry()
                    self.failed.emit(self._request_error(
                        request_kind, str(error)
                    ))
                    return
                self._reset_retry()
                self.succeeded.emit(release)
                return
            if reply.error() != QNetworkReply.NoError:
                if self._retry_transient_failure(reply):
                    return
                self._reset_retry()
                self.failed.emit(self._request_error(
                    request_kind, reply.errorString()
                ))
                return
            if status != 200:
                detail = tr("updates.error.http", status=status)
                self._reset_retry()
                self.failed.emit(self._request_error(request_kind, detail))
                return
        finally:
            reply.deleteLater()

    @staticmethod
    def _request_error(request_kind, detail):
        if request_kind == "web":
            return tr("updates.error.webCheck", detail=detail)
        return str(detail)


class UpdateController(QObject):
    checkStarted = pyqtSignal(bool)
    updateAvailable = pyqtSignal(object)
    upToDate = pyqtSignal(str)
    checkFailed = pyqtSignal(str)

    def __init__(
        self,
        settings,
        current_version,
        *,
        client,
        clock=time.time,
        parent=None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.current_version = str(current_version)
        self.client = client
        self.clock = clock
        self._manual = False
        client.succeeded.connect(self._succeeded)
        client.failed.connect(self._failed)

    def check(self, manual=False):
        now = self.clock()
        if not manual and not automatic_check_due(
            self.settings.get(SETTING_AUTO_CHECK_UPDATES, True),
            self.settings.get(SETTING_UPDATE_NEXT_CHECK_AT, 0),
            now,
        ):
            return False
        started = self.client.fetch()
        if not started:
            if manual and not self._manual:
                self._manual = True
                self.checkStarted.emit(True)
                return True
            return False
        self._manual = bool(manual)
        self.checkStarted.emit(self._manual)
        return True

    def set_auto_enabled(self, enabled):
        self.settings[SETTING_AUTO_CHECK_UPDATES] = bool(enabled)
        if enabled:
            self.settings[SETTING_UPDATE_NEXT_CHECK_AT] = 0
        self._save_settings()

    def ignore_version(self, version):
        self.settings[SETTING_UPDATE_IGNORED_VERSION] = str(version)
        self._save_settings()

    def snooze(self):
        self.settings[SETTING_UPDATE_SNOOZED_UNTIL] = (
            self.clock() + SNOOZE_SECONDS
        )
        self._save_settings()

    def close(self):
        self.cancel_check()

    def cancel_check(self):
        self._manual = False
        self.client.cancel()

    def _succeeded(self, release):
        now = self.clock()
        self._record_success(now, release)
        self._present(release, now)
        self._manual = False

    def _failed(self, detail):
        now = self.clock()
        manual = self._manual
        self._manual = False
        failures = int(self.settings.get(SETTING_UPDATE_FAILURE_COUNT, 0) or 0) + 1
        self.settings[SETTING_UPDATE_LAST_CHECKED_AT] = now
        self.settings[SETTING_UPDATE_FAILURE_COUNT] = failures
        self.settings[SETTING_UPDATE_NEXT_CHECK_AT] = next_automatic_check_at(
            now, failures
        )
        self._save_settings()
        if manual:
            self.checkFailed.emit(str(detail))

    def _record_success(self, now, release):
        self.settings[SETTING_UPDATE_LAST_CHECKED_AT] = now
        self.settings[SETTING_UPDATE_NEXT_CHECK_AT] = (
            now + CHECK_INTERVAL_SECONDS
        )
        self.settings[SETTING_UPDATE_FAILURE_COUNT] = 0
        self.settings[SETTING_UPDATE_CACHED_RELEASE] = release.to_mapping()
        self._save_settings()

    def _present(self, release, now):
        decision = evaluate_update(
            self.current_version,
            release,
            ignored_version=(
                None
                if self._manual
                else self.settings.get(SETTING_UPDATE_IGNORED_VERSION)
            ),
            snoozed_until=(
                0
                if self._manual
                else self.settings.get(SETTING_UPDATE_SNOOZED_UNTIL, 0)
            ),
            now=now,
        )
        if decision.kind is UpdateDecisionKind.AVAILABLE:
            self.updateAvailable.emit(release)
        elif self._manual:
            self.upToDate.emit(str(release.version))

    def _save_settings(self):
        try:
            self.settings.save()
        except OSError:
            pass


class UpdateUiCoordinator(QObject):
    def __init__(
        self,
        window,
        settings,
        current_version,
        status,
        *,
        client=None,
        distribution_strategy=None,
        download_client_factory=InstallerDownloadClient,
    ):
        super().__init__(window)
        self.window = window
        self.status = status
        client = client or GitHubReleaseClient(current_version, parent=self)
        self.controller = UpdateController(
            settings,
            current_version,
            client=client,
            parent=self,
        )
        self.center = None
        self.download_client = None
        self.current_release = None
        self.download_client_factory = download_client_factory
        self._last_check_manual = False
        self._launching_installer = False
        self._center_positioned = False
        self.distribution_strategy = (
            distribution_strategy
            if distribution_strategy is not None
            else detect_distribution_strategy()
        )
        self.controller.checkStarted.connect(self._started)
        self.controller.updateAvailable.connect(self._show_available)
        self.controller.upToDate.connect(self._up_to_date)
        self.controller.checkFailed.connect(self._failed)

    def check_manual(self):
        if (
            self.download_client is not None
            and self.download_client.candidate_path is not None
            and self.current_release is not None
        ):
            center = self._ensure_center()
            center.show_install_ready(self.current_release)
            self._show_active(center)
            return False
        if self.center is not None:
            self._show_active(self.center)
            if self.center.state in {"checking", "downloading"}:
                return False
        return self.controller.check(manual=True)

    def check_automatic(self):
        if not self.window.isVisible() or self.download_client is not None:
            return False
        return self.controller.check(manual=False)

    def set_auto_enabled(self, enabled):
        self.controller.set_auto_enabled(enabled)

    def close(self):
        center = self.center
        self.center = None
        if center is not None:
            center.shutdown()
        self.controller.close()
        if self.download_client is not None and not self._launching_installer:
            self._clear_download()

    def _started(self, manual):
        self._last_check_manual = bool(manual)
        if manual:
            center = self._ensure_center()
            center.show_checking()
            self._show_active(center)

    def _ensure_center(self):
        if self.center is not None:
            return self.center
        center = UpdateCenterWindow()
        self._center_positioned = False
        center.cancelCheckRequested.connect(self._cancel_check)
        center.retryCheckRequested.connect(self._retry_check)
        center.viewRequested.connect(self._view_release)
        center.ignoreRequested.connect(self._ignore_release)
        center.laterRequested.connect(self.controller.snooze)
        center.commandCopied.connect(self._command_copied)
        center.downloadRequested.connect(self._download_installer)
        center.retryDownloadRequested.connect(self._download_installer)
        center.cancelDownloadRequested.connect(self._cancel_download)
        center.installRequested.connect(self._launch_installer)
        center.closed.connect(self._center_gone)
        center.destroyed.connect(self._center_destroyed)
        self.center = center
        return center

    def _clear_center(self, center):
        if self.center is center:
            self.center = None
            self._center_positioned = False

    @pyqtSlot()
    def _center_gone(self):
        # A QObject receiver is disconnected on destruction; a capturing lambda
        # can run during cyclic GC after its closure cells have been cleared.
        self._clear_center(self.sender())

    @pyqtSlot()
    def _center_destroyed(self):
        # Qt passes a temporary QObject wrapper during destroyed(), so identity
        # with the original Python window wrapper is no longer reliable.
        if self.center is not None and sip.isdeleted(self.center):
            self.center = None
            self._center_positioned = False

    @pyqtSlot()
    def _command_copied(self):
        self.status(tr("updates.commandCopied"), 5000)

    @staticmethod
    def _view_release(release):
        QDesktopServices.openUrl(QUrl(release.html_url))

    def _ignore_release(self, release):
        self.controller.ignore_version(release.version)

    def _position_center(self, center):
        if self._center_positioned:
            return
        geometry = center.frameGeometry()
        geometry.moveCenter(self.window.frameGeometry().center())
        center.move(geometry.topLeft())
        self._center_positioned = True

    def _show_active(self, center):
        if center.isMinimized():
            center.showNormal()
        else:
            center.show()
        self._position_center(center)
        center.raise_()
        center.activateWindow()

    def _request_attention(self, center):
        if center.isMinimized():
            center.showNormal()
        else:
            center.show()
        self._position_center(center)
        center.raise_()
        QApplication.alert(center, 0)

    def _cancel_check(self):
        self.controller.cancel_check()

    def _retry_check(self):
        if not self.controller.check(manual=True):
            center = self.center
            if center is not None:
                self._show_active(center)

    def _show_available(self, release):
        self.current_release = release
        center = self._ensure_center()
        center.show_available(release, self.distribution_strategy)
        if self._last_check_manual:
            self._show_active(center)
        else:
            self._request_attention(center)
        self._last_check_manual = False

    def _up_to_date(self, version):
        center = self._ensure_center()
        center.show_up_to_date(version)
        self._show_active(center)
        self._last_check_manual = False

    def _failed(self, detail):
        center = self._ensure_center()
        center.show_check_failure(detail)
        self._show_active(center)
        self._last_check_manual = False

    def _download_installer(self, release):
        if self.download_client is not None:
            if self.download_client.candidate_path is not None:
                self.current_release = release
                center = self._ensure_center()
                center.show_install_ready(release)
                self._request_attention(center)
            return
        self.current_release = release
        client = self.download_client_factory(
            self.controller.current_version,
            parent=self,
        )
        client.progress.connect(self._update_download_progress)
        client.succeeded.connect(self._installer_ready)
        client.failed.connect(self._installer_failed)
        self.download_client = client
        center = self._ensure_center()
        center.show_downloading(release)
        center.show()
        if not client.download(release):
            if self.download_client is client:
                self._clear_download()

    def _update_download_progress(self, received, total):
        if self.center is not None:
            self.center.set_download_progress(received, total)

    def _installer_ready(self, candidate):
        download_client = self.download_client
        if download_client is None or download_client.candidate_path is None:
            self._installer_failed(tr("updates.install.candidateLost"))
            return
        center = self._ensure_center()
        center.show_install_ready(self.current_release)
        self._request_attention(center)

    def _launch_installer(self):
        download_client = self.download_client
        if download_client is None:
            self._installer_failed(tr("updates.install.candidateLost"))
            return
        candidate = download_client.candidate_path
        if candidate is None:
            self._installer_failed(tr("updates.install.candidateLost"))
            return
        self._launching_installer = True
        closed = self.window.close()
        self._launching_installer = False
        if not closed:
            center = self._ensure_center()
            center.show_install_ready(self.current_release)
            self._show_active(center)
            self.status(tr("updates.install.closeBlocked"), 10000)
            return
        result = QProcess.startDetached(str(candidate), [])
        started = result[0] if isinstance(result, tuple) else result
        if not started:
            self.window.show()
            self._installer_failed(tr("updates.install.launchFailed"))
            return
        download_client.take_candidate()

    def _installer_failed(self, detail):
        self.status(tr("updates.install.failed", detail=detail), 10000)
        release = self.current_release
        self._clear_download()
        if release is not None:
            center = self._ensure_center()
            center.show_download_failure(release, detail)
            self._request_attention(center)

    def _cancel_download(self):
        self.status(tr("updates.install.canceled"), 5000)
        release = self.current_release
        self._clear_download()
        if release is not None:
            center = self._ensure_center()
            center.show_download_canceled(release)
            center.show()

    def _clear_download(self):
        client = self.download_client
        self.download_client = None
        if client is not None:
            client.cancel()
            client.deleteLater()
