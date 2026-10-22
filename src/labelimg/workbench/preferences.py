"""Searchable projections of existing settings; no second preference store."""

from PyQt5.QtCore import QSignalBlocker, Qt
from PyQt5.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from labelimg.localization.runtime import language_changed, localize_dialog_buttons, tr
from labelimg.ui.presentation import present_dialog, role, section
from labelimg.ui.query_field import decorate_list_query_field
from labelimg.ui.flow_layout import ActionFlowLayout


class _ActionControl(QCheckBox):
    def __init__(self, action):
        super().__init__()
        self.action = action
        self.clicked.connect(lambda _checked: action.trigger())
        action.changed.connect(self.sync)
        self.sync()

    def sync(self):
        with QSignalBlocker(self):
            self.setChecked(self.action.isChecked())
        self.setText(self.action.text().replace('&', ''))
        self.setToolTip(self.action.toolTip())
        self.setEnabled(self.action.isEnabled())


class PreferencesDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.groups = []
        self.setObjectName('preferencesDialog')
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        decorate_list_query_field(self.search, 'search')
        layout.addWidget(self.search)
        self.note = role(QLabel(), 'supporting')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self._add_group(layout, 'preferences.interface', [window.actions.appearance],
                        menus=[window.menus.language])
        self._add_group(layout, 'preferences.annotation', [window.single_class_mode],
                        menus=[window.menus.labelColorAlgorithm], manage_colors=True)
        self._add_group(layout, 'preferences.display', [
            window.display_label_option, window.hide_at_crosshair_option,
            window.protect_selected_option, window.annotation_display_action,
        ])
        self._add_group(layout, 'preferences.saving', [window.auto_saving, window.auto_update_check])
        self._add_group(layout, 'preferences.workspace', [window.actions.restoreLayout, window.actions.resetAll])
        self.empty = role(QLabel(), 'supporting')
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.search.textChanged.connect(self.filter_rows)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()
        self.resize(620, 740)
        present_dialog(self, minimum_width=480, scroll=True, icon='preferences')

    def _add_group(self, layout, key, actions, *, menus=(), manage_colors=False):
        body = QWidget()
        rows = QVBoxLayout(body)
        rows.setContentsMargins(0, 0, 0, 0)
        action_row = QWidget()
        action_layout = ActionFlowLayout(action_row)
        controls = []
        for action in actions:
            if action.isCheckable():
                control = _ActionControl(action)
            else:
                control = QPushButton()
                control.clicked.connect(self._reset_all if action is self.window.actions.resetAll else action.trigger)
            controls.append((control, action, None))
            if action.isCheckable():
                rows.addWidget(control)
            else:
                action_layout.addWidget(control)
        for menu in menus:
            control = QPushButton()
            control.setMenu(menu)
            controls.append((control, None, menu))
            action_layout.addWidget(control)
        if manage_colors:
            default_control = QPushButton()
            default_control.clicked.connect(self._show_default_category)
            controls.append((default_control, None, 'preferences.defaultCategory'))
            action_layout.addWidget(default_control)
            control = QPushButton()
            control.clicked.connect(self.window.manage_label_colors)
            controls.append((control, None, 'labelColor.manageTitle'))
            action_layout.addWidget(control)
        if action_layout.count():
            rows.addWidget(action_row)
        else:
            action_row.deleteLater()
        frame = section(key, body)
        layout.addWidget(frame)
        self.groups.append((key, frame, controls))

    def _show_default_category(self):
        self.accept()
        self.window.dock.show()
        self.window.dock.raise_()
        self.window.default_category_selector.setFocus(Qt.OtherFocusReason)
        self.window.default_category_selector.showPopup()

    def _reset_all(self):
        self.window.actions.resetAll.trigger()
        if getattr(self.window, '_reset_settings_on_close', False):
            self.accept()

    def retranslate_ui(self, _language=None):
        self.setWindowTitle(tr('preferences.title'))
        self.search.setPlaceholderText(tr('preferences.search'))
        self.search.setAccessibleName(tr('preferences.search'))
        self.note.setText(tr('preferences.immediate'))
        self.empty.setText(tr('preferences.noMatches'))
        localize_dialog_buttons(self.buttons)
        for _key, _frame, controls in self.groups:
            for control, action, menu in controls:
                if isinstance(control, _ActionControl):
                    control.sync()
                elif action is not None:
                    control.setText(action.text().replace('&', ''))
                    control.setToolTip(action.toolTip())
                else:
                    control.setText(tr(menu) if isinstance(menu, str) else menu.title().replace('&', ''))
        self.filter_rows()

    def filter_rows(self, _text=None):
        query = self.search.text().strip().casefold()
        any_visible = False
        for key, frame, controls in self.groups:
            visible = False
            for control, action, menu in controls:
                content = ' '.join((tr(key), control.text(), control.toolTip()))
                if menu is not None and not isinstance(menu, str):
                    content += ' ' + ' '.join(item.text() for item in menu.actions())
                matched = not query or query in content.casefold()
                control.setVisible(matched)
                visible |= matched
            frame.setVisible(visible)
            any_visible |= visible
        self.empty.setVisible(not any_visible)


def show_preferences(window):
    dialog = PreferencesDialog(window)
    dialog.exec_()
    dialog.deleteLater()


def restore_default_layout(window):
    """Restore the initial dock/toolbar arrangement without resetting preferences."""
    window.restoreState(window._default_layout_state)
    window.canvas.setFocus(Qt.OtherFocusReason)
