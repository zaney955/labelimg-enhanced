"""Exclusive Settings menu for automatic label-color allocation."""

from PyQt5.QtWidgets import QActionGroup
from labelimg.ui.menu import Menu as QMenu

from labelimg.annotations.ui.color_algorithms import FIXED, MAXIMIN
from labelimg.localization.runtime import tr
from labelimg.ui.actions import new_action, new_icon, set_action_copy


class LabelColorAlgorithmMenu(QMenu):
    def __init__(self, palette, refresh_colors, parent):
        super().__init__(parent)
        self._palette = palette
        self._refresh_colors = refresh_colors
        self.setIcon(new_icon("color"))
        self.group = QActionGroup(self)
        self.group.setExclusive(True)
        self.actions_by_algorithm = {}
        for algorithm, icon in ((FIXED, "labels"), (MAXIMIN, "color_line")):
            action = new_action(
                self, "", checkable=True, icon=icon,
                slot=lambda checked=False, value=algorithm: self._select(value),
            )
            action.setData(algorithm)
            self.group.addAction(action)
            self.addAction(action)
            self.actions_by_algorithm[algorithm] = action
        self.retranslate_ui()

    def _select(self, algorithm):
        if self._palette.set_algorithm(algorithm):
            self._refresh_colors()

    def retranslate_ui(self):
        self.setTitle(tr("labelColor.algorithm"))
        for algorithm, action in self.actions_by_algorithm.items():
            set_action_copy(
                action,
                tr("labelColor.algorithm." + algorithm),
                tr("labelColor.algorithm." + algorithm + "Detail"),
            )
            action.setChecked(self._palette.algorithm == algorithm)
