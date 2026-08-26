"""Non-modal update notification for one stable GitHub Release."""

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
    QPushButton,
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


class UpdateCheckDialog(QDialog):
    """Single non-modal surface for one user-requested update check."""

    cancelRequested = pyqtSignal()
    retryRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "checking"
        self.setObjectName("updateCheckFeedback")
        self.setWindowTitle(tr("updates.checkTitle"))
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        self.heading = QLabel(self)
        self.heading.setObjectName("updateCheckHeading")
        self.heading.setTextFormat(Qt.PlainText)
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)

        self.detail = QLabel(self)
        self.detail.setObjectName("updateCheckDetail")
        self.detail.setTextFormat(Qt.PlainText)
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.detail)

        self.progress = QProgressBar(self)
        self.progress.setObjectName("updateCheckProgress")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        self.buttons = QDialogButtonBox(self)
        self.cancel_button = self.buttons.addButton(
            tr("standard.cancel"), QDialogButtonBox.RejectRole
        )
        self.retry_button = self.buttons.addButton(
            tr("updates.retry"), QDialogButtonBox.ActionRole
        )
        self.close_button = self.buttons.addButton(
            tr("standard.close"), QDialogButtonBox.RejectRole
        )
        self.cancel_button.clicked.connect(self.reject)
        self.retry_button.clicked.connect(self.retryRequested)
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.buttons)

        self.show_checking()

    @property
    def state(self):
        return self._state

    def show_checking(self):
        self._state = "checking"
        self.setWindowTitle(tr("updates.checkTitle"))
        self.heading.setText(tr("updates.checking"))
        self.detail.clear()
        self.detail.hide()
        self.progress.show()
        self.cancel_button.show()
        self.retry_button.hide()
        self.close_button.hide()
        self.adjustSize()

    def show_up_to_date(self, version):
        self._state = "up_to_date"
        self.heading.setText(tr("updates.upToDate", version=version))
        self.detail.clear()
        self.detail.hide()
        self.progress.hide()
        self.cancel_button.hide()
        self.retry_button.hide()
        self.close_button.show()
        self.close_button.setDefault(True)
        self.adjustSize()

    def show_failure(self, detail):
        self._state = "failed"
        self.heading.setText(tr("updates.checkFailedTitle"))
        self.detail.setText(str(detail))
        self.detail.show()
        self.progress.hide()
        self.cancel_button.hide()
        self.retry_button.show()
        self.close_button.show()
        self.retry_button.setDefault(True)
        self.adjustSize()

    def dismiss(self):
        self._state = "dismissed"
        super().reject()

    def reject(self):
        if self._state == "checking":
            self.cancelRequested.emit()
        super().reject()

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is None:
            return
        geometry = self.frameGeometry()
        geometry.moveCenter(parent.frameGeometry().center())
        self.move(geometry.topLeft())


class UpdateNotificationDialog(QDialog):
    viewRequested = pyqtSignal()
    laterRequested = pyqtSignal()
    ignoreRequested = pyqtSignal()
    commandCopied = pyqtSignal()
    installRequested = pyqtSignal(object)

    def __init__(
        self,
        release,
        parent=None,
        distribution_strategy=DistributionStrategy.PYTHON,
    ):
        super().__init__(parent)
        self.release = release
        self._completed = False
        self.setObjectName("updateNotification")
        self.setWindowTitle(tr("updates.availableTitle"))
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        self.heading = QLabel(tr(
            "updates.availableMessage",
            version=release.version,
        ), self)
        self.heading.setObjectName("updateHeading")
        self.heading.setTextFormat(Qt.PlainText)
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)

        self.summary = QLabel(
            release.summary or tr("updates.noReleaseSummary"), self
        )
        self.summary.setObjectName("updateSummary")
        self.summary.setTextFormat(Qt.PlainText)
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.summary)

        buttons = QDialogButtonBox(self)
        self.view_button = buttons.addButton(
            tr("updates.viewRelease"), QDialogButtonBox.AcceptRole
        )
        self.copy_button = None
        self.install_button = None
        if (
            distribution_strategy is DistributionStrategy.MANAGED_WINDOWS
            and release.installer_url
            and release.sha256_url
        ):
            self.install_button = buttons.addButton(
                tr("updates.install.unsignedButton"),
                QDialogButtonBox.ActionRole,
            )
            self.install_button.clicked.connect(self._install)
        elif (
            distribution_strategy is DistributionStrategy.PYTHON
            and release.wheel_url
        ):
            self.copy_button = buttons.addButton(
                tr("updates.copyCommand"), QDialogButtonBox.ActionRole
            )
            self.copy_button.clicked.connect(self._copy_command)
        self.later_button = buttons.addButton(
            tr("updates.remindLater"), QDialogButtonBox.RejectRole
        )
        self.ignore_button = buttons.addButton(
            tr("updates.ignoreVersion"), QDialogButtonBox.DestructiveRole
        )
        self.view_button.clicked.connect(self._view)
        self.later_button.clicked.connect(self._later)
        self.ignore_button.clicked.connect(self._ignore)
        layout.addWidget(buttons)

    def reject(self):
        if not self._completed:
            self._completed = True
            self.laterRequested.emit()
        super().reject()

    def _view(self):
        self._completed = True
        self.viewRequested.emit()
        self.accept()

    def _later(self):
        self.reject()

    def _ignore(self):
        self._completed = True
        self.ignoreRequested.emit()
        self.accept()

    def _copy_command(self):
        QApplication.clipboard().setText(
            upgrade_command(self.release.wheel_url)
        )
        self.commandCopied.emit()

    def _install(self):
        self._completed = True
        self.installRequested.emit(self.release)
        self.accept()
