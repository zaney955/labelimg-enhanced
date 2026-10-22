"""Independent update center for every visible update state."""

from labelimg.ui.presentation import present_dialog, role

import os
import shlex
import subprocess
import sys

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)

from labelimg.localization.runtime import tr
from labelimg.updates.infrastructure import DistributionStrategy


def upgrade_command(wheel_url, executable=None):
    arguments = [
        executable or sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        str(wheel_url),
    ]
    if os.name == "nt":
        return subprocess.list2cmdline(arguments)
    return shlex.join(arguments)


class UpdateCenterWindow(QDialog):
    """One independent, minimizable window for the complete update flow."""

    cancelCheckRequested = pyqtSignal()
    retryCheckRequested = pyqtSignal()
    viewRequested = pyqtSignal(object)
    laterRequested = pyqtSignal()
    ignoreRequested = pyqtSignal(object)
    commandCopied = pyqtSignal()
    downloadRequested = pyqtSignal(object)
    retryDownloadRequested = pyqtSignal(object)
    cancelDownloadRequested = pyqtSignal()
    installRequested = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self):
        super().__init__(None)
        self._state = "idle"
        self._release = None
        self._close_handled = False
        self._shutting_down = False
        self._closed_emitted = False
        self.setObjectName("updateCenter")
        self.setWindowTitle(tr("updates.centerTitle"))
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        self.heading = QLabel(self)
        self.heading.setObjectName("updateCenterHeading")
        self.heading.setTextFormat(Qt.PlainText)
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)

        self.detail = QLabel(self)
        self.detail.setObjectName("updateCenterDetail")
        self.detail.setTextFormat(Qt.PlainText)
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.detail)

        self.progress = QProgressBar(self)
        self.progress.setObjectName("updateCenterProgress")
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

        self.buttons = QDialogButtonBox(self)
        self.cancel_check_button = self.buttons.addButton(
            tr("standard.cancel"), QDialogButtonBox.RejectRole
        )
        self.retry_check_button = self.buttons.addButton(
            tr("updates.retry"), QDialogButtonBox.ActionRole
        )
        self.view_button = self.buttons.addButton(
            tr("updates.viewRelease"), QDialogButtonBox.ActionRole
        )
        self.copy_button = self.buttons.addButton(
            tr("updates.copyCommand"), QDialogButtonBox.ActionRole
        )
        self.download_button = self.buttons.addButton(
            tr("updates.install.button"), QDialogButtonBox.ActionRole
        )
        self.cancel_download_button = self.buttons.addButton(
            tr("updates.install.cancelDownload"),
            QDialogButtonBox.RejectRole,
        )
        self.retry_download_button = self.buttons.addButton(
            tr("updates.install.retryDownload"),
            QDialogButtonBox.ActionRole,
        )
        self.install_button = self.buttons.addButton(
            tr("updates.install.installNow"), QDialogButtonBox.AcceptRole
        )
        self.later_button = self.buttons.addButton(
            tr("updates.remindLater"), QDialogButtonBox.RejectRole
        )
        self.ignore_button = self.buttons.addButton(
            tr("updates.ignoreVersion"), QDialogButtonBox.DestructiveRole
        )
        self.close_button = self.buttons.addButton(
            tr("standard.close"), QDialogButtonBox.RejectRole
        )
        layout.addWidget(self.buttons)

        self._all_buttons = (
            self.cancel_check_button,
            self.retry_check_button,
            self.view_button,
            self.copy_button,
            self.download_button,
            self.cancel_download_button,
            self.retry_download_button,
            self.install_button,
            self.later_button,
            self.ignore_button,
            self.close_button,
        )
        self.cancel_check_button.clicked.connect(self._cancel_check)
        self.retry_check_button.clicked.connect(self.retryCheckRequested)
        self.view_button.clicked.connect(self._view)
        self.copy_button.clicked.connect(self._copy_command)
        self.download_button.clicked.connect(self._download)
        self.cancel_download_button.clicked.connect(
            self.cancelDownloadRequested
        )
        self.retry_download_button.clicked.connect(self._retry_download)
        self.install_button.clicked.connect(self.installRequested)
        self.later_button.clicked.connect(self._later)
        self.ignore_button.clicked.connect(self._ignore)
        self.close_button.clicked.connect(self.close)
        self._set_state("idle", tr("updates.checking"), progress=False)
        present_dialog(self, minimum_width=520, title=False)
        role(self.heading, "heading")
        for button in (self.download_button, self.install_button, self.view_button):
            role(button, "primary")
        role(self.detail, "supporting")

    @property
    def state(self):
        return self._state

    @property
    def release(self):
        return self._release

    def show_checking(self):
        self._release = None
        self._set_state(
            "checking",
            tr("updates.checking"),
            progress=True,
            buttons=(self.cancel_check_button,),
        )

    def show_up_to_date(self, version):
        self._release = None
        self._set_state(
            "up_to_date",
            tr("updates.upToDate", version=version),
            buttons=(self.close_button,),
        )

    def show_check_failure(self, detail):
        self._release = None
        self._set_state(
            "check_failed",
            tr("updates.checkFailedTitle"),
            detail=str(detail),
            buttons=(self.retry_check_button, self.close_button),
        )

    def show_available(self, release, distribution_strategy):
        self._release = release
        actions = [self.view_button]
        if (
            distribution_strategy is DistributionStrategy.MANAGED_WINDOWS
            and release.installer_url
            and release.sha256_url
        ):
            actions.append(self.download_button)
        elif (
            distribution_strategy is DistributionStrategy.PYTHON
            and release.wheel_url
        ):
            actions.append(self.copy_button)
        actions.extend((self.later_button, self.ignore_button))
        self.later_button.setText(tr("updates.remindLater"))
        self._set_state(
            "available",
            tr("updates.availableMessage", version=release.version),
            buttons=tuple(actions),
        )

    def show_downloading(self, release):
        self._release = release
        self._set_state(
            "downloading",
            tr("updates.install.downloading"),
            progress=True,
            buttons=(self.cancel_download_button,),
        )

    def set_download_progress(self, received, total):
        if self._state != "downloading":
            return
        if total > 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(min(100, int(received * 100 / total)))
        else:
            self.progress.setRange(0, 0)

    def show_download_failure(self, release, detail):
        self._release = release
        self._set_state(
            "download_failed",
            tr("updates.install.failedTitle"),
            detail=str(detail),
            buttons=(
                self.retry_download_button,
                self.view_button,
                self.close_button,
            ),
        )

    def show_download_canceled(self, release):
        self._release = release
        self._set_state(
            "download_canceled",
            tr("updates.install.canceled"),
            buttons=(self.retry_download_button, self.close_button),
        )

    def show_install_ready(self, release):
        self._release = release
        self.later_button.setText(tr("updates.install.later"))
        self._set_state(
            "install_ready",
            tr("updates.install.ready"),
            buttons=(
                self.install_button,
                self.later_button,
                self.view_button,
            ),
        )

    def shutdown(self):
        self._shutting_down = True
        self.close()

    def closeEvent(self, event):
        if self._shutting_down:
            self._emit_closed()
            event.accept()
            return
        if self._state == "downloading":
            event.ignore()
            self.hide()
            return
        if not self._close_handled:
            if self._state == "checking":
                self.cancelCheckRequested.emit()
            elif self._state == "available":
                self.laterRequested.emit()
        self._emit_closed()
        event.accept()

    def _emit_closed(self):
        if not self._closed_emitted:
            self._closed_emitted = True
            self.closed.emit()

    def _set_state(
        self,
        state,
        heading,
        *,
        detail=None,
        progress=False,
        buttons=(),
    ):
        self._state = state
        self._close_handled = False
        self.setWindowTitle(tr("updates.centerTitle"))
        self.heading.setText(str(heading))
        if detail:
            self.detail.setText(str(detail))
            self.detail.show()
        else:
            self.detail.clear()
            self.detail.hide()
        if progress:
            self.progress.setRange(0, 0)
            self.progress.show()
        else:
            self.progress.hide()
        visible = set(buttons)
        for button in self._all_buttons:
            button.setVisible(button in visible)
        self.adjustSize()

    def _cancel_check(self):
        self._close_handled = True
        self.cancelCheckRequested.emit()
        self.close()

    def _view(self):
        if self._release is not None:
            self.viewRequested.emit(self._release)

    def _copy_command(self):
        if self._release is None or not self._release.wheel_url:
            return
        QApplication.clipboard().setText(
            upgrade_command(self._release.wheel_url)
        )
        self.commandCopied.emit()

    def _download(self):
        if self._release is not None:
            self.downloadRequested.emit(self._release)

    def _retry_download(self):
        if self._release is not None:
            self.retryDownloadRequested.emit(self._release)

    def _later(self):
        self._close_handled = True
        if self._state == "available":
            self.laterRequested.emit()
        self.close()

    def _ignore(self):
        if self._release is None:
            return
        self._close_handled = True
        self.ignoreRequested.emit(self._release)
        self.close()
