try:
    from PyQt5.QtCore import QPoint, QRectF, QSize, Qt, QStringListModel
    from PyQt5.QtGui import QColor, QCursor, QFontMetrics, QPainter, QPen
    from PyQt5.QtWidgets import (
        QApplication,
        QAbstractItemView,
        QCompleter,
        QDialog,
        QDialogButtonBox,
        QLineEdit,
        QListView,
        QListWidget,
        QListWidgetItem,
        QStyle,
        QStyledItemDelegate,
        QStyleOptionViewItem,
        QVBoxLayout,
    )
except ImportError:
    from PyQt4.QtCore import QPoint, QRectF, QSize, Qt, QStringListModel
    from PyQt4.QtGui import (
        QApplication,
        QAbstractItemView,
        QColor,
        QCompleter,
        QCursor,
        QDialog,
        QDialogButtonBox,
        QFontMetrics,
        QLineEdit,
        QListView,
        QListWidget,
        QListWidgetItem,
        QPainter,
        QPen,
        QStyle,
        QStyledItemDelegate,
        QStyleOptionViewItem,
        QVBoxLayout,
    )

from labelimg.utils import label_display_color, label_validator, new_icon, trimmed
from labelimg.i18n import language_changed, localize_dialog_buttons


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
    horizontal_padding = 12
    vertical_inset = 2
    horizontal_inset = 4

    def sizeHint(self, option, index):
        view = self.parent()
        if view is not None and view.gridSize().isValid():
            return view.gridSize()
        return super(CandidateLabelDelegate, self).sizeHint(option, index)

    def paint(self, painter, option, index):
        background = QColor(index.data(Qt.BackgroundRole))
        if not background.isValid():
            background = label_display_color(index.data(Qt.DisplayRole))

        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        border_width = 3 if selected else (2 if hovered else 1)

        capsule_rect = QRectF(
            option.rect.adjusted(
                self.horizontal_inset,
                self.vertical_inset,
                -self.horizontal_inset,
                -self.vertical_inset,
            )
        )
        radius = capsule_rect.height() / 2.0

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(background)
        painter.setPen(QPen(_opaque(background), border_width))
        painter.drawRoundedRect(capsule_rect, radius, radius)

        foreground = QColor(index.data(Qt.ForegroundRole))
        if not foreground.isValid():
            foreground = contrast_text_color(
                background,
                option.palette.base().color(),
            )
        painter.setPen(foreground)

        text_rect = capsule_rect.adjusted(
            self.horizontal_padding,
            0,
            -self.horizontal_padding,
            0,
        )
        text = str(index.data(Qt.DisplayRole))
        text = option.fontMetrics.elidedText(
            text,
            Qt.ElideRight,
            max(0, int(text_rect.width())),
        )
        painter.drawText(text_rect, Qt.AlignCenter, text)
        painter.restore()


class CandidateLabelList(QListWidget):
    column_count = 5
    minimum_cell_width = 52
    cell_height = 32

    def __init__(self, parent=None):
        super(CandidateLabelList, self).__init__(parent)
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
        self.setMouseTracking(True)
        self.setItemDelegate(CandidateLabelDelegate(self))
        self.visible_row_count = 0
        self.natural_height = 0

    def ideal_cell_width(self):
        metrics = QFontMetrics(self.font())
        text_width = max(
            (
                _text_width(metrics, self.item(index).text())
                for index in range(self.count())
            ),
            default=0,
        )
        delegate = self.itemDelegate()
        return max(
            self.minimum_cell_width,
            text_width
            + 2 * delegate.horizontal_padding
            + 2 * delegate.horizontal_inset,
        )

    def configure_size(self, maximum_width, maximum_height):
        frame_width = self.frameWidth()
        scroll_extent = self.style().pixelMetric(
            QStyle.PM_ScrollBarExtent,
            None,
            self,
        )
        width_overhead = 2 * frame_width + scroll_extent
        maximum_cell_width = max(
            1,
            (maximum_width - width_overhead - 1) // self.column_count,
        )
        cell_width = min(self.ideal_cell_width(), maximum_cell_width)
        self.setGridSize(QSize(cell_width, self.cell_height))

        self.visible_row_count = (
            (self.count() + self.column_count - 1) // self.column_count
        )
        self.natural_height = (
            self.visible_row_count * self.cell_height + 2 * frame_width
        )
        widget_width = (
            self.column_count * cell_width + width_overhead + 1
        )
        widget_height = min(self.natural_height, maximum_height)
        self.setFixedSize(widget_width, widget_height)

    def sizeHint(self):
        if self.gridSize().isValid():
            return self.size()
        return super(CandidateLabelList, self).sizeHint()


class CandidateLabelDialog(QDialog):
    maximum_screen_width_ratio = 0.8
    maximum_screen_height_ratio = 0.9

    def __init__(self, text="Enter object label", parent=None, list_item=None):
        super(CandidateLabelDialog, self).__init__(parent)

        self.edit = QLineEdit()
        self.edit.setText(text)
        self.edit.setValidator(label_validator())
        self.edit.editingFinished.connect(self.post_process)

        self._completion_model = QStringListModel()
        completer = QCompleter()
        completer.setModel(self._completion_model)
        self.edit.setCompleter(completer)

        self.dialog_layout = layout = QVBoxLayout()
        layout.addWidget(self.edit)
        self.button_box = bb = BB(BB.Ok | BB.Cancel, Qt.Horizontal, self)
        localize_dialog_buttons(bb)
        language_changed.connect(self.retranslate_ui)
        bb.button(BB.Ok).setIcon(new_icon("done"))
        bb.button(BB.Cancel).setIcon(new_icon("undo"))
        bb.accepted.connect(self.validate)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

        self.list_widget = CandidateLabelList(self)
        self.list_widget.setSortingEnabled(True)
        self.list_widget.itemClicked.connect(self.list_item_click)
        self.list_widget.itemDoubleClicked.connect(
            self.list_item_double_click
        )
        layout.addWidget(self.list_widget)

        self.setLayout(layout)
        self.set_candidate_labels(list_item or ())

    def retranslate_ui(self, _language=None):
        localize_dialog_buttons(self.button_box)

    def set_candidate_labels(self, labels):
        labels = tuple(str(label) for label in labels if str(label))
        self._completion_model.setStringList(list(labels))
        self.list_widget.clear()
        base_color = self.list_widget.palette().base().color()
        for label in labels:
            item = QListWidgetItem(label)
            background = label_display_color(label)
            item.setData(Qt.BackgroundRole, background)
            item.setData(
                Qt.ForegroundRole,
                contrast_text_color(background, base_color),
            )
            item.setToolTip(label)
            self.list_widget.addItem(item)
        self.list_widget.setVisible(bool(labels))
        self.update_candidate_geometry()

    def available_screen_geometry(self):
        screen = None
        if hasattr(QApplication, "screenAt"):
            screen = QApplication.screenAt(QCursor.pos())
        if screen is None and hasattr(QApplication, "primaryScreen"):
            screen = QApplication.primaryScreen()
        if screen is not None:
            return screen.availableGeometry()
        return QApplication.desktop().availableGeometry(self)

    def update_candidate_geometry(self):
        if self.list_widget.count() == 0:
            self.dialog_layout.activate()
            self.adjustSize()
            return

        screen_geometry = self.available_screen_geometry()
        maximum_dialog_width = int(
            screen_geometry.width() * self.maximum_screen_width_ratio
        )
        maximum_dialog_height = int(
            screen_geometry.height() * self.maximum_screen_height_ratio
        )

        margins = self.dialog_layout.contentsMargins()
        candidate_maximum_width = max(
            1,
            maximum_dialog_width - margins.left() - margins.right(),
        )
        chrome_height = (
            margins.top()
            + margins.bottom()
            + self.edit.sizeHint().height()
            + self.button_box.sizeHint().height()
            + 2 * self.dialog_layout.spacing()
        )
        candidate_maximum_height = max(
            CandidateLabelList.cell_height + 2 * self.list_widget.frameWidth(),
            maximum_dialog_height - chrome_height,
        )

        self.list_widget.configure_size(
            candidate_maximum_width,
            candidate_maximum_height,
        )
        self.dialog_layout.activate()
        height_overflow = (
            self.sizeHint().height() - maximum_dialog_height
        )
        if height_overflow > 0:
            minimum_candidate_height = (
                CandidateLabelList.cell_height
                + 2 * self.list_widget.frameWidth()
            )
            self.list_widget.setFixedHeight(
                max(
                    minimum_candidate_height,
                    self.list_widget.height() - height_overflow,
                )
            )
        self.setMaximumSize(maximum_dialog_width, maximum_dialog_height)
        self.dialog_layout.activate()
        self.adjustSize()

    def validate(self):
        if trimmed(self.edit.text()):
            self.accept()

    def post_process(self):
        self.edit.setText(trimmed(self.edit.text()))

    def choose(self, text="", move=True):
        """
        Show the dialog and return the entered label, or None when cancelled.
        """
        self.edit.setText(text)
        self.edit.setSelection(0, len(text))
        self.edit.setFocus(Qt.PopupFocusReason)
        self.update_candidate_geometry()
        if move:
            cursor_pos = QCursor.pos()
            screen_geometry = self.available_screen_geometry()
            max_x = screen_geometry.right() - self.width() + 1
            max_y = screen_geometry.bottom() - self.height() + 1
            cursor_pos.setX(
                min(max(cursor_pos.x(), screen_geometry.left()), max_x)
            )
            cursor_pos.setY(
                min(max(cursor_pos.y(), screen_geometry.top()), max_y)
            )
            self.move(cursor_pos)
        return trimmed(self.edit.text()) if self.exec_() else None

    def list_item_click(self, item):
        self.list_widget.setCurrentItem(item)
        self.edit.setText(trimmed(item.text()))

    def list_item_double_click(self, item):
        self.list_item_click(item)
        self.validate()
