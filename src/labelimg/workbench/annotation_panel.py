"""Compose the annotation dock's global, creation, list and selection controls."""

from labelimg.ui.theme import theme_style

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QAction,
    QStyle,
    QStyleOption,
)
from labelimg.ui.menu import Menu as QMenu

from labelimg.annotations.ui.default_category_selector import DefaultCategorySelector
from labelimg.annotations.ui.label_group_list import LabelGroupListWidget
from labelimg.localization.runtime import tr
from labelimg.ui.actions import new_icon
from labelimg.ui.query_field import decorate_list_query_field
from labelimg.ui.presentation import present_panel
from labelimg.ui.panels import PanelCountLabel, PanelHeader, panel_body, panel_context, panel_list


class _SummaryLabel(PanelCountLabel):
    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def paintEvent(self, event):
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)
        painter.setFont(self.font())
        painter.setPen(self.palette().windowText().color())
        painter.drawText(
            self.contentsRect(),
            Qt.AlignVCenter | Qt.AlignLeft,
            self.fontMetrics().elidedText(
                self.text(), Qt.ElideRight, self.contentsRect().width()
            ),
        )


def build_annotation_panel(window):
    w = window
    w.dock = QDockWidget(tr("boxLabelText"), w)
    w.dock.setObjectName(tr("labels"))
    w.dock.setMinimumWidth(320)
    container, layout = panel_body("annotationPanelSurface")
    w.annotation_title = QLabel(tr("boxLabelText"))
    w.annotation_title.setObjectName("annotationPanelTitle")
    w.label_summary_label = _SummaryLabel()
    w.label_summary_label.setObjectName("annotationPanelSummary")
    w.annotation_header = PanelHeader(
        w.dock, "annotation-panel", w.annotation_title, w.label_summary_label
    )
    w.annotation_header.setObjectName("annotationPanelHeader")
    context, controls = panel_context()
    w.annotation_context = context

    def button(name):
        result = QToolButton()
        result.setObjectName(name)
        result.setAutoRaise(True)
        result.setIconSize(QSize(18, 18))
        result.setFixedSize(26, 26)
        return result

    w.visibility_button = button("annotationVisibilityButton")
    w.label_color_button = button("labelColorPaletteButton")
    w.label_color_button.setIcon(new_icon("color"))
    w.label_color_button.clicked.connect(w.manage_label_colors)
    w.near_duplicate_more_button = button("nearDuplicateMoreButton")
    w.near_duplicate_more_button.setIcon(new_icon("more"))
    w.near_duplicate_more_button.setPopupMode(QToolButton.InstantPopup)
    w.near_duplicate_more_menu = QMenu(w.near_duplicate_more_button)
    w.restore_near_duplicate_action = QAction(w)
    w.restore_near_duplicate_action.setEnabled(False)
    w.restore_near_duplicate_action.triggered.connect(
        w.restore_current_near_duplicate_dismissals
    )
    w.near_duplicate_more_menu.addAction(w.restore_near_duplicate_action)
    w.near_duplicate_more_button.setMenu(w.near_duplicate_more_menu)
    for control in (
        w.visibility_button,
        w.label_color_button,
        w.near_duplicate_more_button,
    ):
        w.annotation_header.add_control(control)

    w.default_label_row = QFrame()
    w.default_label_row.setObjectName("annotationCreationSettings")
    defaults = QHBoxLayout(w.default_label_row)
    defaults.setContentsMargins(0, 0, 0, 0)
    defaults.setSpacing(10)
    w.default_category_caption = QLabel(tr("annotationPanel.defaultCategory"))
    w.default_category_caption.setObjectName("annotationCreationCaption")
    w.default_category_selector = DefaultCategorySelector(
        lambda text: w.candidate_label_dialog.choose(text)
    )
    w.default_category_caption.setBuddy(w.default_category_selector)
    defaults.addWidget(w.default_category_caption)
    defaults.addWidget(w.default_category_selector, 1)
    w.default_category_selector.set_candidate_labels(w.candidate_labels)
    controls.addWidget(w.default_label_row)

    w.label_filter = QLineEdit()
    w.label_filter.setPlaceholderText(tr("labels.filter"))
    w.label_filter_icon_action = decorate_list_query_field(w.label_filter, "filter")
    controls.addWidget(w.label_filter)
    layout.addWidget(context)
    w.label_list = LabelGroupListWidget()
    w.label_list.setFrameShape(QFrame.NoFrame)
    layout.addWidget(panel_list(w.label_list), 1)

    w.annotation_selection_bar = QFrame()
    w.annotation_selection_bar.setObjectName("annotationSelectionBar")
    w.annotation_selection_bar.setProperty("uiRole", "panelFooter")
    selected = QHBoxLayout(w.annotation_selection_bar)
    selected.setContentsMargins(10, 5, 10, 5)
    selected.setSpacing(4)
    w.annotation_selection_label = QLabel()
    w.annotation_selection_label.setObjectName("annotationSelectionCount")
    selected.addWidget(w.annotation_selection_label)
    selected.addStretch()
    w.edit_button = button("annotationEditButton")
    w.edit_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    w.edit_button.setMinimumWidth(68)
    w.edit_button.setMaximumWidth(100)
    w.copy_button = button("annotationCopyButton")
    w.delete_button = button("annotationDeleteButton")
    w.diffc_button = QCheckBox(tr("useDifficult"))
    w.diffc_button.setEnabled(False)
    w.diffc_button.stateChanged.connect(w.button_state)
    for control in (w.edit_button, w.copy_button, w.delete_button, w.diffc_button):
        selected.addWidget(control)
    w.annotation_selection_bar.hide()
    layout.addWidget(w.annotation_selection_bar)
    w.dock.setWidget(container)
    present_panel(
        w.dock,
        theme_style("""
        QLabel#annotationSelectionCount { color: ${accent_hover}; font-size: ${font_supporting}px; }
        QWidget#annotationCreationSettings { background: transparent; border: none; }
        QLabel#annotationCreationCaption { color: ${muted}; font-size: ${font_supporting}px; }
        QToolButton { border: 1px solid transparent; border-radius: 4px; padding: 0; }
        QToolButton:hover { background: ${selected}; }
        QToolButton:focus { border-color: ${accent}; }
        QToolButton::menu-indicator { image: none; }
        QComboBox { min-height: 28px; padding: 0 8px; border: none;
            border-radius: 4px; background: ${panel_header}; color: ${text}; }
        QComboBox::drop-down { border: none; width: 24px; }
        QComboBox::down-arrow { image: url(:/chevron-down); width: 16px; height: 16px; }
        QLineEdit { min-height: 28px; padding: 0 6px 0 0; border: 1px solid ${divider};
            border-radius: 4px; background: ${surface}; color: ${text}; }
        QLineEdit:focus { border-color: ${accent}; }
        QCheckBox { spacing: 4px; }
    """),
    )
    w.label_filter.textChanged.connect(w.label_list.set_filter_text)
    w.label_list.summaryChanged.connect(lambda text: update_annotation_summary(w, text))
    w.label_list.selectionRequested.connect(w.label_selection_requested)
    w.label_list.visibilityRequested.connect(w.label_visibility_requested)
    w.label_list.groupEditRequested.connect(w.edit_label_group)
    w.label_list.instanceEditRequested.connect(w.edit_shape_label)
    w.label_list.contextMenuRequested.connect(w.pop_label_group_menu)
    update_annotation_summary(w, w.label_list.summary_text())


def update_annotation_summary(window, detail):
    window.label_summary_label.setText(window.label_list.summary_text(compact=True))
    window.label_summary_label.setToolTip(detail)
    window.label_summary_label.setAccessibleName(detail)
