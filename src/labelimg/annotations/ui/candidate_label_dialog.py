"""Compact category picker with stable geometry and live candidate filtering."""

from labelimg.ui.presentation import present_surface, role

from labelimg.ui.theme import theme_changed, theme_style

from PyQt5.QtCore import QEvent, QRectF, QSize, Qt, QSignalBlocker
from PyQt5.QtGui import QColor, QCursor, QFontMetrics, QPainter, QPainterPath, QPalette, QPen
from PyQt5.QtWidgets import (
    QApplication, QAbstractItemView, QDialog, QDialogButtonBox, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
    QStackedWidget, QStyle, QStyledItemDelegate, QVBoxLayout,
)

from labelimg.annotations.ui.style import (
    LABEL_INDICATOR_FILL_ALPHA, label_display_color, label_validator,
    natural_label_key, trimmed,
)
from labelimg.localization.runtime import language_changed, localize_dialog_buttons, tr
from labelimg.ui.query_field import decorate_list_query_field
from labelimg.ui.metrics import Metric, dp, scale_changed


BB = QDialogButtonBox


def _text_width(font_metrics, text):
    if hasattr(font_metrics, "horizontalAdvance"):
        return font_metrics.horizontalAdvance(text)
    return font_metrics.width(text)


def _opaque(color):
    color = QColor(color)
    color.setAlpha(255)
    return color


def _relative_luminance(color):
    channels = []
    for component in (color.redF(), color.greenF(), color.blueF()):
        if component <= 0.03928:
            channels.append(component / 12.92)
        else:
            channels.append(((component + 0.055) / 1.055) ** 2.4)
    return (
        0.2126 * channels[0]
        + 0.7152 * channels[1]
        + 0.0722 * channels[2]
    )


def contrast_text_color(background, base):
    """Return black or white, accounting for the translucent background."""
    background = QColor(background)
    base = QColor(base)
    alpha = background.alphaF()
    composite = QColor(
        round(background.red() * alpha + base.red() * (1.0 - alpha)),
        round(background.green() * alpha + base.green() * (1.0 - alpha)),
        round(background.blue() * alpha + base.blue() * (1.0 - alpha)),
    )
    luminance = _relative_luminance(composite)
    black_contrast = (luminance + 0.05) / 0.05
    white_contrast = 1.05 / (luminance + 0.05)
    return QColor(Qt.black if black_contrast >= white_contrast else Qt.white)


class CandidateLabelDelegate(QStyledItemDelegate):
    horizontal_padding = Metric(6)
    horizontal_inset = Metric(3)
    vertical_inset = Metric(3)
    stripe_width = Metric(8)
    outline_width = Metric(1.4)
    radius = Metric(4)

    def sizeHint(self, option, index):
        view = self.parent()
        if view is not None and view.gridSize().isValid():
            return view.gridSize()
        return super().sizeHint(option, index)

    def paint(self, painter, option, index):
        color = QColor(index.data(Qt.BackgroundRole))
        if not color.isValid():
            color = label_display_color(index.data(Qt.DisplayRole))
        color.setAlpha(255)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        box = QRectF(option.rect.adjusted(
            self.horizontal_inset, self.vertical_inset,
            -self.horizontal_inset, -self.vertical_inset,
        ))
        path = QPainterPath()
        path.addRoundedRect(box, self.radius, self.radius)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        fill = QColor(color)
        fill.setAlpha(LABEL_INDICATOR_FILL_ALPHA)
        painter.fillPath(path, fill)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(QRectF(box.left(), box.top(), self.stripe_width, box.height()), color)
        painter.restore()
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(color, 2.2 if selected else 1.8 if hovered else self.outline_width))
        painter.drawPath(path)
        painter.setFont(option.font)
        painter.setPen(option.palette.color(QPalette.Text))
        text_box = box.adjusted(
            self.stripe_width + self.horizontal_padding + self.outline_width / 2, 0,
            -self.horizontal_padding - self.outline_width / 2, 0,
        )
        text = option.fontMetrics.elidedText(
            str(index.data(Qt.DisplayRole)), Qt.ElideRight, max(0, int(text_box.width())),
        )
        painter.drawText(text_box, Qt.AlignCenter, text)
        painter.restore()


class CandidateLabelList(QListWidget):
    column_count = 4
    minimum_cell_width = Metric(52)
    cell_height = Metric(36)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setWordWrap(False)
        self.setSpacing(0)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.NoFrame)
        self.setMouseTracking(True)
        self.setItemDelegate(CandidateLabelDelegate(self))
        self.visible_row_count = 0
        self.natural_height = 0
        self.layout_column_count = 1

    def ideal_cell_width(self, labels=None):
        if labels is None:
            labels = (self.item(index).text() for index in range(self.count()))
        metrics = QFontMetrics(self.font())
        text_width = max((_text_width(metrics, label) for label in labels), default=0)
        delegate = self.itemDelegate()
        return max(self.minimum_cell_width, text_width + delegate.stripe_width
                   + 2 * delegate.horizontal_padding + 2 * delegate.horizontal_inset + 4)

    def configure_size(self, maximum_width, maximum_height, labels=None):
        # Measure the full candidate pool once, not the changing filtered subset.
        labels = tuple(labels) if labels is not None else tuple(
            self.item(index).text() for index in range(self.count())
        )
        ideal = self.ideal_cell_width(labels)
        frame = 2 * self.frameWidth()
        scroll = self.style().pixelMetric(QStyle.PM_ScrollBarExtent, None, self)
        available = max(1, maximum_width - frame - scroll - 2)
        columns = max(1, min(self.column_count, len(labels) or 1, available // ideal))
        cell_width = min(ideal, available)
        self.layout_column_count = columns
        rows = max(1, (len(labels) + columns - 1) // columns)
        self.visible_row_count = rows if labels else 0
        self.natural_height = rows * self.cell_height + frame
        height = min(self.natural_height, maximum_height)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if self.natural_height > height else Qt.ScrollBarAlwaysOff
        )
        width = columns * cell_width + frame + 2
        if self.natural_height > height:
            width += scroll
        self.setGridSize(QSize(cell_width, self.cell_height))
        self.setFixedSize(min(width, maximum_width), height)

    def sizeHint(self):
        return self.size() if self.gridSize().isValid() else super().sizeHint()


class CandidateLabelDialog(QDialog):
    maximum_screen_width_ratio = 0.8
    maximum_screen_height_ratio = 0.9

    def __init__(self, text="", parent=None, list_item=None, color_for_label=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setProperty("uiScaleDynamicGeometry", True)
        scale_changed.connect(self._scale_changed)
        self.setObjectName("candidateLabelDialog")
        self._color_for_label = color_for_label or label_display_color
        self._candidate_labels = ()
        self._colors = {}
        self._query = ""
        stylesheet = theme_style("""
            QDialog#candidateLabelDialog { background: ${surface}; }
            QLabel { color: ${text}; background: transparent; }
            QLabel#candidateTitle { font-size: ${font_heading}px; font-weight: 600; }
            QLabel#candidateCount, QLabel#candidateEmpty { color: ${muted}; }
            QLabel#candidateCount { font-size: ${font_supporting}px; }
            QLineEdit { min-height: 32px; padding: 0 8px 0 0; border: 1px solid ${border};
                border-radius: 5px; color: ${text}; background: ${surface}; }
            QLineEdit:focus { border-color: ${accent}; }
            QListWidget { border: none; background: transparent; outline: 0; }
            QPushButton { min-height: 29px; min-width: 64px; padding: 0 5px;
                border: 1px solid ${border}; border-radius: 4px;
                color: ${text}; background: ${surface}; }
            QPushButton:hover { background: ${background}; }
            QPushButton#candidateConfirm { color: ${on_accent}; background: ${accent}; border-color: ${accent}; }
            QPushButton#candidateConfirm:hover { background: ${accent_hover}; }
            QPushButton#candidateConfirm:disabled { color: ${disabled_text}; background: ${disabled_background}; border-color: ${disabled_background}; }
            QFrame#candidateDivider { background: ${divider}; min-height: 1px; max-height: 1px; border: none; }
        """)
        self.dialog_layout = layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        self.header_layout = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setObjectName("candidateTitle")
        self.count_label = QLabel()
        self.count_label.setObjectName("candidateCount")
        self.header_layout.addWidget(self.title_label)
        self.header_layout.addStretch()
        self.header_layout.addWidget(self.count_label)
        layout.addLayout(self.header_layout)

        self.edit = QLineEdit(text)
        self.edit.setValidator(label_validator())
        self.edit.editingFinished.connect(self.post_process)
        decorate_list_query_field(self.edit, "filter")
        self.edit.installEventFilter(self)
        layout.addWidget(self.edit)

        self.list_widget = CandidateLabelList(self)
        self.list_widget.setProperty("uiScaleDynamicGeometry", True)
        self.list_widget.installEventFilter(self)
        self.list_widget.itemClicked.connect(self.list_item_click)
        self.list_widget.itemDoubleClicked.connect(self.list_item_double_click)
        self.list_widget.currentItemChanged.connect(self._current_candidate_changed)
        self.empty_label = QLabel()
        self.empty_label.setObjectName("candidateEmpty")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.candidate_stack = QStackedWidget()
        self.candidate_stack.setProperty("uiScaleDynamicGeometry", True)
        self.candidate_stack.addWidget(self.list_widget)
        self.candidate_stack.addWidget(self.empty_label)
        layout.addWidget(self.candidate_stack, 0, Qt.AlignLeft)

        self.divider = QFrame()
        self.divider.setObjectName("candidateDivider")
        layout.addWidget(self.divider)
        self.button_box = BB(BB.Ok | BB.Cancel, Qt.Horizontal, self)
        self.button_box.setProperty("uiScaleDynamicGeometry", True)
        self.button_box.button(BB.Ok).setObjectName("candidateConfirm")
        role(self.button_box.button(BB.Ok), 'primary')
        self.button_box.button(BB.Ok).setDefault(True)
        self.button_box.accepted.connect(self.validate)
        self.button_box.rejected.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(self.button_box)
        layout.addLayout(footer)
        self.setTabOrder(self.edit, self.list_widget)
        self.setTabOrder(self.list_widget, self.button_box.button(BB.Ok))
        self.setTabOrder(self.button_box.button(BB.Ok), self.button_box.button(BB.Cancel))
        self.edit.textChanged.connect(self._filter_candidates)
        language_changed.connect(self.retranslate_ui)
        theme_changed.connect(self._theme_changed)
        present_surface(self, stylesheet)
        self.retranslate_ui()
        self.set_candidate_labels(list_item or ())

    def retranslate_ui(self, _language=None):
        self.setWindowTitle(tr("labelChooser.title"))
        self.title_label.setText(tr("labelChooser.title"))
        self.edit.setPlaceholderText(tr("labelChooser.placeholder"))
        self.edit.setAccessibleName(tr("labelChooser.name"))
        self.list_widget.setAccessibleName(tr("labelChooser.candidates"))
        localize_dialog_buttons(self.button_box)
        self._update_feedback()
        self.update_candidate_geometry()

    def set_candidate_labels(self, labels):
        self._candidate_labels = tuple(sorted(
            {str(label) for label in labels if str(label)}, key=natural_label_key,
        ))
        self._colors = {
            label: _opaque(self._color_for_label(label)) for label in self._candidate_labels
        }
        if not self.isVisible():
            self._query = ""
        self._populate_candidates()
        self.update_candidate_geometry()

    def refresh_colors(self):
        self.set_candidate_labels(self._candidate_labels)

    def _theme_changed(self, _identifier):
        for row in range(self.list_widget.count()):
            self.list_widget.item(row).setData(Qt.ForegroundRole, self.palette().color(QPalette.Text))

    def _populate_candidates(self):
        query = self._query
        labels = [label for label in self._candidate_labels if query in label.casefold()]
        if query:
            labels.sort(key=lambda label: (
                0 if label.casefold() == query else 1 if label.casefold().startswith(query) else 2,
                natural_label_key(label),
            ))
        # Rebuilding must not overwrite the draft with a programmatic selection.
        with QSignalBlocker(self.list_widget):
            self.list_widget.clear()
            for label in labels:
                item = QListWidgetItem(label)
                item.setData(Qt.BackgroundRole, self._colors[label])
                item.setData(Qt.ForegroundRole, self.palette().color(QPalette.Text))
                item.setToolTip(label)
                self.list_widget.addItem(item)
                if label == self.edit.text():
                    self.list_widget.setCurrentItem(item)
        self.candidate_stack.setCurrentWidget(self.list_widget if labels else self.empty_label)
        self._update_feedback()

    def _filter_candidates(self, text):
        self._query = trimmed(text).casefold()
        self._populate_candidates()

    def _update_feedback(self):
        count, total = self.list_widget.count(), len(self._candidate_labels)
        self.count_label.setText(tr(
            "labelChooser.filteredCount" if self._query else "labelChooser.count",
            count=count, total=total,
        ))
        self.empty_label.setText(tr("labelChooser.noMatch" if self._query else "labelChooser.empty"))
        self.button_box.button(BB.Ok).setEnabled(bool(trimmed(self.edit.text())))

    def _set_label_text(self, text):
        with QSignalBlocker(self.edit):
            self.edit.setText(trimmed(text))
        self._update_feedback()

    def _current_candidate_changed(self, current, _previous):
        if current is not None:
            self._set_label_text(current.text())

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress and watched is self.edit:
            if event.key() in (Qt.Key_Down, Qt.Key_Up) and self.list_widget.count():
                row = self.list_widget.currentRow()
                if row < 0:
                    row = 0 if event.key() == Qt.Key_Down else self.list_widget.count() - 1
                else:
                    row += 1 if event.key() == Qt.Key_Down else -1
                self.list_widget.setCurrentRow(max(0, min(row, self.list_widget.count() - 1)))
                self.list_widget.scrollToItem(self.list_widget.currentItem())
                self.edit.selectAll()
                return True
        if event.type() == QEvent.KeyPress and watched is self.list_widget:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.validate()
                return True
        return super().eventFilter(watched, event)

    def available_screen_geometry(self):
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        return screen.availableGeometry() if screen else QApplication.desktop().availableGeometry(self)

    def update_candidate_geometry(self):
        self.ensurePolished()
        for button in self.button_box.buttons():
            button.ensurePolished()
        self.button_box.setFixedWidth(self.button_box.sizeHint().width())
        self.dialog_layout.activate()
        screen = self.available_screen_geometry()
        maximum_width = int(screen.width() * self.maximum_screen_width_ratio)
        maximum_height = int(screen.height() * self.maximum_screen_height_ratio)
        self.setMaximumSize(maximum_width, maximum_height)
        self.setMinimumWidth(min(dp(300), maximum_width))
        margins = self.dialog_layout.contentsMargins()
        chrome_height = (
            margins.top() + margins.bottom() + self.header_layout.sizeHint().height()
            + self.edit.sizeHint().height() + self.divider.minimumHeight()
            + self.button_box.sizeHint().height() + 4 * self.dialog_layout.spacing()
        )
        self.list_widget.configure_size(
            max(1, maximum_width - margins.left() - margins.right()),
            max(self.list_widget.cell_height, maximum_height - chrome_height),
            self._candidate_labels,
        )
        self.candidate_stack.setFixedSize(self.list_widget.size())
        self.dialog_layout.activate()
        self.adjustSize()
        self.resize(self.sizeHint().expandedTo(self.minimumSize()).boundedTo(self.maximumSize()))

    def _scale_changed(self, _percent):
        self.update_candidate_geometry()

    def validate(self):
        if trimmed(self.edit.text()):
            self.accept()

    def post_process(self):
        self._set_label_text(self.edit.text())

    def choose(self, text="", move=True):
        """Show all candidates initially; filtering starts with the next edit."""
        self._set_label_text(text)
        self._query = ""
        self._populate_candidates()
        self.edit.selectAll()
        self.edit.setFocus(Qt.PopupFocusReason)
        self.update_candidate_geometry()
        if move:
            position = QCursor.pos()
            screen = self.available_screen_geometry()
            position.setX(min(max(position.x(), screen.left()), screen.right() - self.width() + 1))
            position.setY(min(max(position.y(), screen.top()), screen.bottom() - self.height() + 1))
            self.move(position)
        return trimmed(self.edit.text()) if self.exec_() else None

    def list_item_click(self, item):
        self.list_widget.setCurrentItem(item)
        self._set_label_text(item.text())

    def list_item_double_click(self, item):
        self.list_item_click(item)
        self.validate()
