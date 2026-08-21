"""Non-modal member chooser for one near-duplicate annotation cluster."""

from PyQt5.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QShortcut,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from labelimg.canvas import CATEGORY_CONFLICT
from labelimg.localization.runtime import language_changed, tr


class _MemberRow(QWidget):
    visibilityRequested = pyqtSignal(object, bool)

    def __init__(self, shape, ordinal, visible, parent=None):
        super(_MemberRow, self).__init__(parent)
        self.shape = shape
        self.visible = bool(visible)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 3, 2)
        layout.setSpacing(6)
        self.ordinal_label = QLabel("#%d" % ordinal)
        self.label_label = QLabel(str(shape.label))
        self.label_label.setMinimumWidth(80)
        self.visibility_button = QToolButton()
        self.visibility_button.setAutoRaise(True)
        self.visibility_button.setFixedSize(QSize(24, 24))
        self.visibility_button.clicked.connect(self._toggle_visibility)
        layout.addWidget(self.ordinal_label)
        layout.addWidget(self.label_label, 1)
        layout.addWidget(self.visibility_button)
        self.retranslate_ui()

    def set_visible_state(self, visible):
        self.visible = bool(visible)
        self.retranslate_ui()

    def retranslate_ui(self):
        self.visibility_button.setText("◉" if self.visible else "⊘")
        self.visibility_button.setToolTip(
            tr(
                "nearDuplicate.hideMember"
                if self.visible
                else "nearDuplicate.showMember"
            )
        )

    def _toggle_visibility(self):
        self.visibilityRequested.emit(self.shape, not self.visible)


class NearDuplicateChooser(QFrame):
    """A popup that exposes one explicit member target at a time."""

    selectionRequested = pyqtSignal(object, object)
    visibilityRequested = pyqtSignal(object, bool)
    editRequested = pyqtSignal(object)
    deleteRequested = pyqtSignal(object)
    dismissRequested = pyqtSignal(object)
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super(NearDuplicateChooser, self).__init__(
            parent,
            Qt.Popup | Qt.FramelessWindowHint,
        )
        self.setObjectName("nearDuplicateChooser")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFocusPolicy(Qt.StrongFocus)
        self.cluster = None
        self._visible_shapes = set()
        self._rows = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.title_label = QLabel()
        self.title_label.setObjectName("nearDuplicateChooserTitle")
        self.member_list = QListWidget()
        self.member_list.setObjectName("nearDuplicateMemberList")
        self.member_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.member_list.itemClicked.connect(self._activate_item)
        self.member_list.installEventFilter(self)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(5)
        self.edit_button = QPushButton()
        self.delete_button = QPushButton()
        self.dismiss_button = QPushButton()
        self.edit_button.clicked.connect(self.edit_current)
        self.delete_button.clicked.connect(self.delete_current)
        self.dismiss_button.clicked.connect(self.dismiss_cluster)
        button_row.addWidget(self.edit_button)
        button_row.addWidget(self.delete_button)
        button_row.addStretch(1)
        button_row.addWidget(self.dismiss_button)

        layout.addWidget(self.title_label)
        layout.addWidget(self.member_list)
        layout.addLayout(button_row)
        self.resize(340, 250)
        language_changed.connect(self._language_changed)
        QShortcut(QKeySequence(Qt.Key_F2), self, activated=self.edit_current)
        QShortcut(QKeySequence(Qt.Key_Delete), self, activated=self.delete_current)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.close)

    @property
    def current_shape(self):
        item = self.member_list.currentItem()
        return None if item is None else item.data(Qt.UserRole)

    def show_cluster(
        self,
        cluster,
        visible_shapes,
        preferred_shape=None,
        global_position=None,
    ):
        self.cluster = cluster
        self._visible_shapes = set(visible_shapes)
        self._populate(preferred_shape)
        self.retranslate_ui()
        self._place(global_position)
        self.show()
        self.raise_()
        self.member_list.setFocus(Qt.PopupFocusReason)

    def refresh_cluster(self, cluster, visible_shapes, preferred_shape=None):
        if cluster is None or len(cluster.members) < 2:
            self.close()
            return
        self.cluster = cluster
        self._visible_shapes = set(visible_shapes)
        self._populate(preferred_shape)
        self.retranslate_ui()

    def _populate(self, preferred_shape=None):
        current = preferred_shape or self.current_shape
        self.member_list.clear()
        self._rows.clear()
        if self.cluster is None:
            return
        for ordinal, shape in enumerate(self.cluster.members, 1):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, shape)
            item.setSizeHint(QSize(300, 30))
            item.setToolTip(_geometry_text(shape))
            self.member_list.addItem(item)
            row = _MemberRow(
                shape,
                ordinal,
                shape in self._visible_shapes,
                self.member_list,
            )
            row.setToolTip(_geometry_text(shape))
            row.visibilityRequested.connect(self.visibilityRequested)
            self.member_list.setItemWidget(item, row)
            self._rows[shape] = row
            if shape is current:
                self.member_list.setCurrentItem(item)
        if self.member_list.currentItem() is None and self.member_list.count():
            self.member_list.setCurrentRow(0)

    def retranslate_ui(self):
        if self.cluster is not None:
            conflict = self.cluster.risk == CATEGORY_CONFLICT
            self.title_label.setText(tr(
                "nearDuplicate.conflictTitle"
                if conflict
                else "nearDuplicate.duplicateTitle",
                count=len(self.cluster.members),
            ))
        self.edit_button.setText(tr("nearDuplicate.editMember"))
        self.delete_button.setText(tr("nearDuplicate.deleteMember"))
        self.dismiss_button.setText(tr("nearDuplicate.dismissSession"))
        for row in self._rows.values():
            row.retranslate_ui()

    def select_current(self):
        shape = self.current_shape
        if shape is not None and self.cluster is not None:
            self.selectionRequested.emit(self.cluster, shape)

    def edit_current(self):
        shape = self.current_shape
        if shape is not None:
            self.editRequested.emit(shape)

    def delete_current(self):
        shape = self.current_shape
        if shape is not None:
            self.deleteRequested.emit(shape)

    def dismiss_cluster(self):
        if self.cluster is not None:
            self.dismissRequested.emit(self.cluster)

    def eventFilter(self, watched, event):
        if watched is self.member_list and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.select_current()
                return True
            if event.key() in (Qt.Key_Up, Qt.Key_Down):
                delta = -1 if event.key() == Qt.Key_Up else 1
                row = self.member_list.currentRow()
                row = max(
                    0,
                    min(self.member_list.count() - 1, row + delta),
                )
                self.member_list.setCurrentRow(row)
                self.select_current()
                return True
            if event.key() == Qt.Key_Space:
                shape = self.current_shape
                if shape is not None:
                    self.visibilityRequested.emit(
                        shape,
                        shape not in self._visible_shapes,
                    )
                return True
        return super(NearDuplicateChooser, self).eventFilter(watched, event)

    def closeEvent(self, event):
        self.closed.emit()
        super(NearDuplicateChooser, self).closeEvent(event)

    def _activate_item(self, item):
        self.member_list.setCurrentItem(item)
        self.select_current()

    def _place(self, global_position):
        if global_position is None:
            if self.parentWidget() is not None:
                global_position = self.parentWidget().mapToGlobal(
                    self.parentWidget().rect().center()
                )
            else:
                global_position = QApplication.primaryScreen().availableGeometry().center()
        screen = QApplication.screenAt(global_position)
        available = (
            screen.availableGeometry()
            if screen is not None
            else QApplication.desktop().availableGeometry(global_position)
        )
        x = min(global_position.x() + 8, available.right() - self.width())
        y = min(global_position.y() + 8, available.bottom() - self.height())
        self.move(max(available.left(), x), max(available.top(), y))

    def _language_changed(self, _language):
        self.retranslate_ui()


def _geometry_text(shape):
    bounds = shape.bounding_rect()
    values = (
        bounds.x(),
        bounds.y(),
        bounds.width(),
        bounds.height(),
    )
    return "x:%s  y:%s  w:%s  h:%s" % tuple(
        _format_number(value) for value in values
    )


def _format_number(value):
    rounded = round(float(value))
    if abs(float(value) - rounded) < 0.01:
        return str(int(rounded))
    return ("%.1f" % float(value)).rstrip("0").rstrip(".")
