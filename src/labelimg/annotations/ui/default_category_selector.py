"""Window-local default category, independent of the workspace vocabulary."""

from PyQt5.QtCore import QSignalBlocker, pyqtSignal
from PyQt5.QtWidgets import QComboBox

from labelimg.annotations.ui.style import natural_label_key, trimmed
from labelimg.localization.runtime import language_changed, tr


class DefaultCategorySelector(QComboBox):
    fixedLabelChanged = pyqtSignal(object)

    def __init__(self, choose_label, parent=None):
        super().__init__(parent)
        self._choose_label = choose_label
        self._fixed_label = None
        self._labels = ()
        self.setObjectName("defaultCategorySelector")
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(8)
        self.activated[int].connect(self._activate_choice)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    @property
    def fixed_label(self):
        return self._fixed_label

    def set_fixed_label(self, label):
        label = trimmed(str(label)) if label is not None else None
        label = label or None
        changed = self._fixed_label != label
        self._fixed_label = label
        self._rebuild()
        if changed:
            self.fixedLabelChanged.emit(label)

    def set_candidate_labels(self, labels):
        labels = tuple(sorted(set(labels), key=natural_label_key))
        if labels != self._labels:
            self._labels = labels
            self._rebuild()

    def retranslate_ui(self, _language=None):
        self.setAccessibleName(tr("annotationPanel.defaultCategory"))
        self._rebuild()

    def _rebuild(self):
        choices = set(self._labels)
        if self._fixed_label:
            choices.add(self._fixed_label)
        with QSignalBlocker(self):
            self.clear()
            self.addItem(tr("annotationPanel.chooseEachTime"), ("each", None))
            selected = 0
            for label in sorted(choices, key=natural_label_key):
                self.addItem(tr("annotationPanel.fixedCategory", label=label), ("fixed", label))
                if label == self._fixed_label:
                    selected = self.count() - 1
            self.addItem(tr("annotationPanel.setFixedCategory"), ("custom", None))
            self.setCurrentIndex(selected)
        self.setToolTip(self.currentText())

    def _activate_choice(self, index):
        kind, label = self.itemData(index)
        if kind == "custom":
            label = self._choose_label(self._fixed_label or "")
            if label is None:
                self._rebuild()
                return
        self.set_fixed_label(label)
