"""Explicit workspace scope and a reviewable label replacement preview."""

from PyQt5.QtCore import QEventLoop, Qt
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QLabel, QLineEdit, QProgressDialog, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QHeaderView,
)

from labelimg.annotations.ui.errors import annotation_error_text
from labelimg.localization.runtime import localize_dialog_buttons, tr


class LabelReplaceDialog(QDialog):
    def __init__(self, labels, *, selected_count, preview, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("labelReplace.title"))
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.plan = None
        self._preview = preview
        layout = QVBoxLayout(self)
        explanation = QLabel(tr("labelReplace.explanation"))
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        form = QFormLayout()
        self.old_label = QComboBox()
        self.old_label.setEditable(True)
        self.old_label.addItems(labels)
        self.old_label.setCurrentIndex(-1)
        self.new_label = QLineEdit()
        self.scope = QComboBox()
        self.scope.addItem(tr("labelReplace.all"), "all")
        if selected_count:
            self.scope.addItem(tr("labelReplace.selected", count=selected_count), "selected")
        form.addRow(tr("labelReplace.old"), self.old_label)
        form.addRow(tr("labelReplace.new"), self.new_label)
        form.addRow(tr("labelReplace.scope"), self.scope)
        layout.addLayout(form)
        self.preview_button = QPushButton(tr("labelReplace.preview"))
        self.preview_button.clicked.connect(self.preview)
        layout.addWidget(self.preview_button)
        self.summary = QLabel(tr("labelReplace.previewFirst"))
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.PlainText)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels((tr("labelReplace.image"), tr("labelReplace.count")))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)
        note = QLabel(tr("labelReplace.persistenceNote"))
        note.setWordWrap(True)
        layout.addWidget(note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        localize_dialog_buttons(self.buttons)
        self.apply_button = self.buttons.button(QDialogButtonBox.Ok)
        self.apply_button.setText(tr("labelReplace.apply"))
        self.apply_button.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.old_label.currentTextChanged.connect(self.invalidate)
        self.new_label.textChanged.connect(self.invalidate)
        self.scope.currentIndexChanged.connect(self.invalidate)
        self.resize(640, 480)
        self.invalidate()

    def invalidate(self, *_args):
        self.plan = None
        self.apply_button.setEnabled(False)
        self.table.setRowCount(0)
        self.summary.setText(tr("labelReplace.previewFirst"))
        old, new = self.old_label.currentText().strip(), self.new_label.text().strip()
        self.preview_button.setEnabled(bool(old and new and old != new))

    def preview(self):
        self.invalidate()
        progress = QProgressDialog(tr("labelReplace.scanning"), "", 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()

        def report(value, total):
            progress.setMaximum(total)
            progress.setValue(value)
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

        try:
            self.plan = self._preview(
                self.scope.currentData(), self.old_label.currentText().strip(),
                self.new_label.text().strip(), report,
            )
        except Exception as error:
            self.summary.setText(annotation_error_text(error))
            return
        finally:
            progress.close()
        self.summary.setText(tr(
            "labelReplace.summary", old=self.plan.old_label, new=self.plan.new_label,
            images=len(self.plan.items), boxes=self.plan.box_count,
        ) + ("\n" + tr("labelReplace.merge") if self.plan.merges else ""))
        self.table.setRowCount(len(self.plan.items))
        for row, item in enumerate(self.plan.items):
            self.table.setItem(row, 0, QTableWidgetItem(item.image_path))
            self.table.setItem(row, 1, QTableWidgetItem(str(item.count)))
        self.apply_button.setEnabled(bool(self.plan.items))
