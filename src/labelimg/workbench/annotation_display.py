"""Annotation appearance controls with live preview and cancel rollback."""

from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QVBoxLayout,
)

from labelimg.localization.runtime import localize_dialog_buttons, tr
from labelimg.ui.presentation import present_dialog, role


def show_annotation_display_settings(window):
    canvas = window.canvas
    previous = (canvas.annotation_line_width, canvas.annotation_font_size)
    dialog = QDialog(window)
    dialog.setWindowTitle(tr('annotationDisplay.title'))
    layout = QVBoxLayout(dialog)
    form = QFormLayout()
    layout.addLayout(form)
    description = QLabel(tr('ui.appearance.preview'), dialog)
    description.setToolTip(tr('annotationDisplay.detail'))
    role(description, 'supporting')
    width = QDoubleSpinBox(dialog)
    width.setObjectName('annotationLineWidth')
    width.setRange(0.5, 6.0)
    width.setSingleStep(0.5)
    width.setDecimals(1)
    width.setSuffix(' px')
    width.setValue(previous[0])
    font = QDoubleSpinBox(dialog)
    font.setObjectName('annotationFontSize')
    font.setRange(6.0, 128.0)
    font.setSingleStep(1.0)
    font.setDecimals(1)
    font.setSuffix(' pt')
    font.setValue(previous[1])
    width.setAccessibleName(tr('annotationDisplay.lineWidth'))
    font.setAccessibleName(tr('annotationDisplay.fontSize'))
    form.addRow(tr('annotationDisplay.lineWidth'), width)
    form.addRow(tr('annotationDisplay.fontSize'), font)
    layout.addWidget(description)

    def preview():
        canvas.set_annotation_style(width.value(), font.value())

    width.valueChanged.connect(preview)
    font.valueChanged.connect(preview)
    buttons = QDialogButtonBox(
        QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults,
        parent=dialog,
    )
    localize_dialog_buttons(buttons)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)

    def defaults():
        width.setValue(1.5)
        font.setValue(25.0)

    buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(defaults)
    layout.addWidget(buttons)
    present_dialog(dialog, primary=buttons.button(QDialogButtonBox.Ok), minimum_width=420, icon="annotation-display")
    if dialog.exec_() != QDialog.Accepted:
        canvas.set_annotation_style(*previous)
    dialog.deleteLater()
