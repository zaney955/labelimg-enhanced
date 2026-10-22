"""Independent update center for every visible update state."""

from labelimg.ui.presentation import present_dialog, role, icon_tile
from labelimg.ui.icons import IconLabel
from labelimg.ui.theme import apply_theme_style, theme_style
from labelimg import __version__

import os
import shlex
import subprocess
import sys

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)

from labelimg.localization.runtime import tr, language_changed
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
        self.setMinimumWidth(560)
        self._latest_version = None

        layout = QVBoxLayout(self)
        brand = QHBoxLayout()
        brand.setSpacing(9)
        brand.addWidget(IconLabel("app", size=28))
        brand.addWidget(role(QLabel("LabelImg Enhanced"), "sectionTitle"))
        brand.addStretch(1)
        self.current_version = role(QLabel(), "supporting")
        brand.addWidget(self.current_version)
        layout.addLayout(brand)
        layout.addSpacing(10)
        hero = QHBoxLayout()
        hero.setSpacing(16)
        self.status_icon = icon_tile("check-updates", size=56, icon_size=32)
        self.status_icon.setObjectName("updateStatusIcon")
        hero.addWidget(self.status_icon, 0, Qt.AlignVCenter)
        status = QVBoxLayout()
        status.setSpacing(5)
        self.heading = role(QLabel(self), "heading")
        self.heading.setObjectName("updateCenterHeading")
        self.heading.setTextFormat(Qt.PlainText)
        self.heading.setWordWrap(True)
        status.addWidget(self.heading)
        self.version_label = role(QLabel(), "supporting")
        self.version_label.setTextFormat(Qt.PlainText)
        self.version_label.setWordWrap(True)
        status.addWidget(self.version_label)
        hero.addLayout(status, 1)
        layout.addLayout(hero)
        layout.addSpacing(4)
        self.detail = QLabel(self)
        self.detail.setObjectName("updateCenterDetail")
        self.detail.setTextFormat(Qt.PlainText)
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.detail_area = QScrollArea()
        self.detail_area.setWidgetResizable(True)
        self.detail_area.setWidget(self.detail)
        self.detail_area.setFixedHeight(100)
        layout.addWidget(self.detail_area)
        self.progress_row = QFrame()
        progress_layout = QHBoxLayout(self.progress_row)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(12)
        self.progress = QProgressBar(self)
        self.progress.setObjectName("updateCenterProgress")
        self.progress.setTextVisible(False)
        progress_layout.addWidget(self.progress, 1)
        self.progress_caption = role(QLabel(), "supporting")
        progress_layout.addWidget(self.progress_caption)
        layout.addWidget(self.progress_row)
        layout.addStretch(1)
        self.secondary_actions = QFrame()
        self.secondary_layout = QHBoxLayout(self.secondary_actions)
        self.secondary_layout.setContentsMargins(0, 0, 0, 0)
        self.secondary_layout.setSpacing(12)
        layout.addWidget(self.secondary_actions)

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
        self.cancel_download_button.clicked.connect(self.cancelDownloadRequested)
        self.retry_download_button.clicked.connect(self._retry_download)
        self.install_button.clicked.connect(self.installRequested)
        self.later_button.clicked.connect(self._later)
        self.ignore_button.clicked.connect(self._ignore)
        self.close_button.clicked.connect(self.close)
        self.buttons.removeButton(self.ignore_button)
        self.secondary_layout.addWidget(self.ignore_button)
        self.secondary_layout.addStretch(1)
        apply_theme_style(
            self,
            theme_style("""
            QFrame#updateStatusIcon { border-radius: 14px; background: ${selected}; }
            QFrame#updateStatusIcon[statusTone="success"] { background: ${icon_success_tint}; }
            QFrame#updateStatusIcon[statusTone="warning"] { background: ${icon_warning_tint}; }
            QPushButton[uiRole="updateLink"] { border: none; background: transparent; color: ${accent}; min-width: 0; padding: 0 2px; }
            QPushButton[uiRole="updateLink"]:hover { color: ${accent_hover}; text-decoration: underline; }
            QPushButton[uiRole="updateLink"]:focus { border: 1px solid ${accent}; }
            QProgressBar#updateCenterProgress { min-height: 6px; max-height: 6px; border: none; border-radius: 3px; }
            QLabel#updateCenterDetail { padding: 10px; color: ${muted}; background: ${background}; }
        """),
        )
        self.resize(580, 240)
        present_dialog(self, minimum_width=560, title=False)
        language_changed.connect(self._refresh_copy)
        self._set_state("idle", tr("updates.checking"), progress=False)

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
        self._latest_version = str(version)
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
        elif distribution_strategy is DistributionStrategy.PYTHON and release.wheel_url:
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
            self.progress_caption.setText(f"{self.progress.value()}%")
        else:
            self.progress.setRange(0, 0)
            self.progress_caption.clear()

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
        self._fallback_heading = str(heading)
        if state != "up_to_date":
            self._latest_version = None
        self.detail.setText(str(detail or ""))
        self.detail_area.setVisible(bool(detail))
        self.progress_row.setVisible(progress)
        self.progress_caption.clear()
        if progress:
            self.progress.setRange(0, 0)
        visible = set(buttons)
        priority = (
            self.install_button,
            self.download_button,
            self.copy_button,
            self.retry_download_button,
            self.retry_check_button,
            self.view_button,
        )
        primary = next((button for button in priority if button in visible), None)
        self.buttons.removeButton(self.view_button)
        self.secondary_layout.removeWidget(self.view_button)
        if primary is self.view_button:
            self.buttons.addButton(self.view_button, QDialogButtonBox.ActionRole)
        else:
            self.secondary_layout.insertWidget(0, self.view_button)
        for button in self._all_buttons:
            role(
                button,
                (
                    "primary"
                    if button is primary
                    else (
                        "updateLink"
                        if button in (self.view_button, self.ignore_button)
                        else "secondary"
                    )
                ),
            )
            button.setVisible(button in visible)
            button.updateGeometry()
        self.buttons.layout().invalidate()
        self.buttons.updateGeometry()
        self.secondary_layout.invalidate()
        self.secondary_actions.setVisible(
            self.ignore_button in visible
            or (self.view_button in visible and primary is not self.view_button)
        )
        tone = (
            "success"
            if state in ("up_to_date", "install_ready")
            else "warning" if state in ("check_failed", "download_failed") else "accent"
        )
        self.status_icon.setProperty("statusTone", tone)
        self.status_icon.style().unpolish(self.status_icon)
        self.status_icon.style().polish(self.status_icon)
        glyph = (
            "done"
            if tone == "success"
            else "status-warning" if tone == "warning" else "check-updates"
        )
        label = self.status_icon.findChild(IconLabel)
        label._icon_name = glyph
        label.update()
        self._refresh_copy()
        self.layout().activate()
        self.resize(580, max(240, self.minimumSizeHint().height()))

    def _refresh_copy(self, _language=None):
        self.setWindowTitle(tr("updates.centerTitle"))
        states = {
            "idle": "updates.checking",
            "checking": "updates.checking",
            "up_to_date": "updates.status.upToDate",
            "available": "updates.status.available",
            "downloading": "updates.status.downloading",
            "install_ready": "updates.status.ready",
            "check_failed": "updates.checkFailedTitle",
            "download_failed": "updates.install.failedTitle",
            "download_canceled": "updates.install.canceled",
        }
        self.heading.setText(
            tr(states[self._state]) if self._state in states else self._fallback_heading
        )
        self.current_version.setText(tr("updates.currentVersion", version=__version__))
        self.current_version.setVisible(self._state != "up_to_date")
        version = (
            str(self._release.version)
            if self._release is not None
            else self._latest_version
        )
        self.version_label.setText(
            tr(
                (
                    "updates.version"
                    if self._state == "up_to_date"
                    else "updates.latestVersion"
                ),
                version=version,
            )
            if version
            else ""
        )
        self.version_label.setVisible(bool(version))
        labels = (
            (self.cancel_check_button, "standard.cancel"),
            (self.retry_check_button, "updates.retry"),
            (self.view_button, "updates.viewRelease"),
            (self.copy_button, "updates.copyCommand"),
            (self.download_button, "updates.install.button"),
            (self.cancel_download_button, "updates.install.cancelDownload"),
            (self.retry_download_button, "updates.install.retryDownload"),
            (self.install_button, "updates.install.installNow"),
            (
                self.later_button,
                (
                    "updates.install.later"
                    if self._state == "install_ready"
                    else "updates.remindLater"
                ),
            ),
            (self.ignore_button, "updates.ignoreVersion"),
            (self.close_button, "standard.close"),
        )
        for button, key in labels:
            button.setText(tr(key))
            button.setAutoDefault(False)

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
        QApplication.clipboard().setText(upgrade_command(self._release.wheel_url))
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
