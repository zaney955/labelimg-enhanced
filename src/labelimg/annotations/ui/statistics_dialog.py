"""Scrollable category charts and numeric details for annotation statistics."""

from labelimg.ui.presentation import present_dialog, role, compact_paths, metric_card

import math

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QProgressDialog, QPushButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from labelimg.annotations.application.statistics import StatisticsCanceled, StatisticsError
from labelimg.annotations.ui.errors import annotation_error_text
from labelimg.localization.runtime import language_changed, localize_dialog_buttons, tr


def statistics_error_text(error):
    return tr("annotationStats.error." + error.reason) if isinstance(error, StatisticsError) else annotation_error_text(error)


class _NumberItem(QTableWidgetItem):
    def __init__(self, value, text=None):
        super().__init__(str(value) if text is None else text)
        self.setData(Qt.UserRole, value)
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        return self.data(Qt.UserRole) < other.data(Qt.UserRole)


class CategoryBarChart(QWidget):
    ROW_HEIGHT = 36
    TOP = 32

    def __init__(self, color_for_label, parent=None):
        super().__init__(parent)
        self.rows = ()
        self.metric = "boxes"
        self.color_for_label = color_for_label
        self.setMouseTracking(True)
        self.setAccessibleName(tr("annotationStats.chart"))

    def set_rows(self, rows, metric):
        self.rows = tuple(rows)
        self.metric = metric
        self.setMinimumHeight(max(180, len(rows) * self.ROW_HEIGHT + self.TOP + 30))
        self.setAccessibleDescription("\n".join("%s: %s" % (row.label, getattr(row, metric)) for row in rows))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        text_color = self.palette().text().color()
        painter.setPen(text_color)
        if not self.rows:
            painter.drawText(self.rect().adjusted(12, 12, -12, -12), Qt.AlignCenter | Qt.TextWordWrap, tr("annotationStats.noCategories"))
            return
        metrics = painter.fontMetrics()
        label_width = min(max(110, max(metrics.horizontalAdvance(row.label) for row in self.rows) + 16), min(240, int(self.width() * .35)))
        maximum = max(getattr(row, self.metric) for row in self.rows)
        tick_step = max(1, math.ceil(maximum / 4))
        axis_maximum = max(1, math.ceil(maximum / tick_step) * tick_step)
        count_width = max(58, metrics.horizontalAdvance(f"{maximum:,}") + 20)
        plot_width = max(1, self.width() - label_width - count_width - 16)
        for tick in range(0, axis_maximum + 1, tick_step):
            x = label_width + plot_width * tick / axis_maximum
            painter.setPen(QPen(self.palette().midlight().color(), 1))
            painter.drawLine(QPointF(x, self.TOP), QPointF(x, self.height() - 16))
            painter.setPen(text_color)
            painter.drawText(QRectF(x - 35, 4, 70, 22), Qt.AlignCenter, f"{tick:,}")
        for index, row in enumerate(self.rows):
            y = self.TOP + index * self.ROW_HEIGHT
            label = metrics.elidedText(row.label, Qt.ElideMiddle, label_width - 16)
            painter.setPen(text_color)
            painter.drawText(QRectF(6, y, label_width - 18, self.ROW_HEIGHT), Qt.AlignRight | Qt.AlignVCenter, label)
            value = getattr(row, self.metric)
            width = plot_width * value / axis_maximum
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self.color_for_label(row.label)))
            painter.drawRoundedRect(QRectF(label_width, y + 8, width, 20), 3, 3)
            painter.setPen(text_color)
            painter.drawText(QRectF(label_width + width + 6, y, count_width, self.ROW_HEIGHT), Qt.AlignLeft | Qt.AlignVCenter, f"{value:,}")

    def mouseMoveEvent(self, event):
        index = (event.pos().y() - self.TOP) // self.ROW_HEIGHT
        if 0 <= index < len(self.rows):
            row = self.rows[index]
            self.setToolTip(tr("annotationStats.barTooltip", label=row.label, boxes=row.boxes, images=row.images))
        else:
            self.setToolTip("")
        super().mouseMoveEvent(event)


class AnnotationStatisticsDialog(QDialog):
    def __init__(self, collect, *, image_dir, annotation_dir, color_for_label, parent=None):
        super().__init__(parent)
        self._collect = collect
        self.image_dir = image_dir
        self.annotation_dir = annotation_dir
        self.statistics = None
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        layout = QVBoxLayout(self)
        self.scope = QLabel()
        self.scope.setTextFormat(Qt.PlainText)
        self.scope.setWordWrap(True)
        role(self.scope, "supporting")
        self.scope.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.scope)
        counters = QHBoxLayout()
        self.image_count = metric_card("ui.stats.images")
        self.category_count = metric_card("ui.stats.categories")
        self.box_count = metric_card("ui.stats.boxes")
        for card in (self.image_count, self.category_count, self.box_count):
            counters.addWidget(card, 1)
        layout.addLayout(counters)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.PlainText)
        self.summary.setWordWrap(True)
        role(self.summary, "supporting")
        layout.addWidget(self.summary)
        controls = QHBoxLayout()
        self.metric = QComboBox()
        self.metric.addItem("", "boxes")
        self.metric.addItem("", "images")
        self.metric.currentIndexChanged.connect(self._render)
        self.search = QLineEdit()
        self.search.textChanged.connect(self._render)
        self.refresh_button = QPushButton()
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.metric)
        controls.addWidget(self.search, 1)
        controls.addWidget(self.refresh_button)
        layout.addLayout(controls)
        self.tabs = QTabWidget()
        self.chart = CategoryBarChart(color_for_label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.chart)
        self.table = QTableWidget(0, 4)
        self.table.horizontalHeader().setSortIndicator(1, Qt.DescendingOrder)
        self.issues = QTableWidget(0, 3)
        for table in (self.table, self.issues):
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabs.addTab(scroll, "")
        self.tabs.addTab(self.table, "")
        self.tabs.addTab(self.issues, "")
        layout.addWidget(self.tabs, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        role(self.note, "supporting")
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        self.buttons = buttons
        footer = QHBoxLayout()
        footer.addWidget(self.note, 1)
        footer.addWidget(buttons)
        layout.addLayout(footer)
        self.resize(920, 650)
        language_changed.connect(self.retranslate)
        self.retranslate()
        present_dialog(self, scroll=True, icon="annotation-statistics")

    def retranslate(self, *_args):
        self.setWindowTitle(tr("annotationStats.title"))
        compact_paths(self.scope, self.image_dir, self.annotation_dir)
        self.metric.setItemText(0, tr("annotationStats.boxes"))
        self.metric.setItemText(1, tr("annotationStats.images"))
        self.search.setPlaceholderText(tr("annotationStats.search"))
        self.search.setAccessibleName(tr("annotationStats.search"))
        self.refresh_button.setText(tr("annotationStats.refresh"))
        for index, key in enumerate(("chart", "details", "issues")):
            self.tabs.setTabText(index, tr("annotationStats." + key))
        self.table.setHorizontalHeaderLabels(tuple(tr("annotationStats." + key) for key in ("category", "boxes", "images", "share")))
        self.issues.setHorizontalHeaderLabels(tuple(tr("annotationStats." + key) for key in ("imagePath", "annotationPath", "diagnostic")))
        self.note.setText(tr("ui.stats.readOnly"))
        self.note.setToolTip(tr("annotationStats.note"))
        self.chart.setAccessibleName(tr("annotationStats.chart"))
        localize_dialog_buttons(self.buttons)
        self._render()

    def refresh(self):
        self.statistics = None
        self._render()
        self.refresh_button.setEnabled(False)
        progress = QProgressDialog(tr("annotationStats.scanning"), tr("common.cancel"), 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        def report(value, total):
            progress.setMaximum(total)
            progress.setValue(value)
            QApplication.processEvents()
            if progress.wasCanceled():
                raise StatisticsCanceled()

        try:
            self.statistics = self._collect(report)
        except StatisticsCanceled:
            self.summary.setText(tr("annotationStats.canceled"))
        except Exception as error:
            self.summary.setText(statistics_error_text(error))
        else:
            self._render()
        finally:
            progress.close()
            progress.deleteLater()
            self.refresh_button.setEnabled(True)

    def _render(self, *_args):
        result = self.statistics
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.issues.setRowCount(0)
        if result is None:
            for card in (self.image_count, self.category_count, self.box_count):
                card.value.setText("—")
            self.summary.setText(tr("annotationStats.ready"))
            self.chart.set_rows((), self.metric.currentData())
            return
        query = self.search.text().casefold().strip()
        rows = [row for row in result.categories if query in row.label.casefold()]
        metric = self.metric.currentData()
        rows.sort(key=lambda row: (-getattr(row, metric), row.label.casefold(), row.label))
        self.chart.set_rows(rows, metric)
        for card, value in ((self.image_count, result.total_images),
                            (self.category_count, len(result.categories)),
                            (self.box_count, result.total_boxes)):
            card.value.setText(f"{value:,}")
        self.summary.setText(tr(
            "ui.stats.details",
            images=result.total_images, annotated=result.annotated_images, empty=result.empty_images,
            missing=result.missing_images, failed=len(result.issues), unsaved=result.unsaved_images,
            shown=len(rows),
        ))
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            percent = row.boxes / max(1, result.total_boxes) * 100
            self.table.setItem(index, 0, QTableWidgetItem(row.label))
            self.table.setItem(index, 1, _NumberItem(row.boxes))
            self.table.setItem(index, 2, _NumberItem(row.images))
            self.table.setItem(index, 3, _NumberItem(percent, f"{percent:.1f}%"))
        self.table.setSortingEnabled(True)
        self.table.sortItems(1 if metric == "boxes" else 2, Qt.DescendingOrder)
        self.issues.setRowCount(len(result.issues))
        for index, issue in enumerate(result.issues):
            for column, value in enumerate((issue.image_path, issue.annotation_path, statistics_error_text(issue.error))):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.issues.setItem(index, column, item)


def show_annotation_statistics(window):
    from labelimg.annotations.application.statistics import AnnotationStatisticsCollector

    if window.annotation_editing.pending or window.annotation_editing.edit_open:
        window.status(tr("status.finishEdit"))
        return
    if not window.dir_name and not window.file_path:
        return
    collector = AnnotationStatisticsCollector(window.annotation_workspace, window.annotation_editing)

    def collect(progress):
        # Discover from disk at refresh time, independently of filters/index readiness.
        paths = window.scan_all_images(window.dir_name) if window.dir_name else (window.file_path,)
        return collector.collect(paths, progress)

    dialog = AnnotationStatisticsDialog(
        collect, image_dir=window.dir_name or window.file_path,
        annotation_dir=window.default_save_dir or window.dir_name or tr("annotationStats.besideImage"),
        color_for_label=window.label_color_palette.color, parent=window,
    )
    window.auto_save_timer.stop()
    window.annotation_editing.set_pending("Annotation statistics", dialog.reject)
    window._sync_annotation_history_ui()
    QTimer.singleShot(0, dialog.refresh)
    try:
        dialog.exec_()
    finally:
        window.annotation_editing.clear_pending()
        window._sync_annotation_history_ui()
        dialog.deleteLater()
