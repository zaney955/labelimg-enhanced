"""Local, bilingual Help dialogs for the annotation workbench."""

from labelimg.ui.theme import apply_theme_style, theme_style


from labelimg.ui.presentation import present_dialog, role
from labelimg.ui.icons import IconLabel
from labelimg.ui.actions import new_icon

from dataclasses import dataclass

from PyQt5.QtCore import Qt, QUrl, QT_VERSION_STR
from PyQt5.QtGui import QKeySequence, QDesktopServices
from PyQt5.QtWidgets import (
    QAction,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from labelimg.localization.runtime import localize_dialog_buttons, tr
from labelimg.ui.actions import plain_action_text


REPOSITORY_URL = "https://github.com/zaney955/labelimg-enhanced"


@dataclass(frozen=True)
class ShortcutRow:
    """One keyboard-operated command as presented in Help."""

    action: str
    keys: str
    explanation: str


@dataclass(frozen=True)
class ShortcutSection:
    """Keyboard-operated commands sharing one scope."""

    title: str
    rows: tuple


_ACTION_SECTIONS = (
    (
        "shortcuts.section.workspace",
        (
            "openDir",
            "open",
            "searchImages",
            "save",
            "saveAs",
            "close",
            "deleteImg",
            "quit",
        ),
    ),
    (
        "shortcuts.section.navigation",
        ("openPrev", "openNext", "verify", "question"),
    ),
    (
        "shortcuts.section.annotation",
        (
            "undoAnnotation",
            "redoAnnotation",
            "copyAnnotations",
            "pasteAnnotations",
            "edit",
            "copy",
            "delete",
            "drawSquares",
        ),
    ),
    (
        "shortcuts.section.canvasTools",
        ("selectTool", "panTool", "create", "cropImage"),
    ),
    (
        "shortcuts.section.view",
        (
            "displayLabel",
            "magnifier",
            "labels",
            "hideAll",
            "showAll",
            "zoomIn",
            "zoomOut",
            "zoomOrg",
            "fitWindow",
            "fitWidth",
        ),
    ),
)


_CONTEXT_SECTIONS = (
    (
        "shortcuts.section.canvasContext",
        (
            ("shortcuts.keys.contextMenu", "shortcuts.canvas.contextMenu", "shortcuts.canvas.contextMenuDetail"),
            ("shortcuts.keys.overlapBadge", "shortcuts.canvas.nearDuplicate", "shortcuts.canvas.nearDuplicateDetail"),
            ("shortcuts.keys.doubleClick", "shortcuts.canvas.editLabel", "shortcuts.canvas.editLabelDetail"),
            ("shortcuts.keys.controlHold", "shortcuts.canvas.multiSelect", "shortcuts.canvas.multiSelectDetail"),
            ("Esc", "shortcuts.canvas.cancel", "shortcuts.canvas.cancelDetail"),
            ("Enter", "shortcuts.canvas.finish", "shortcuts.canvas.finishDetail"),
            ("shortcuts.keys.arrows", "shortcuts.canvas.nudge", "shortcuts.canvas.nudgeDetail"),
            ("shortcuts.keys.mouseWheel", "shortcuts.canvas.wheelScroll", "shortcuts.canvas.wheelScrollDetail"),
            ("shortcuts.keys.shiftWheel", "shortcuts.canvas.wheelScrollHorizontal", "shortcuts.canvas.wheelScrollHorizontalDetail"),
            ("shortcuts.keys.controlWheel", "shortcuts.canvas.wheelZoom", "shortcuts.canvas.wheelZoomDetail"),
        ),
    ),
    (
        "shortcuts.section.zoomControlContext",
        (
            ("shortcuts.keys.mouseWheel", "shortcuts.zoomControl.wheel", "shortcuts.zoomControl.wheelDetail"),
        ),
    ),
    (
        "shortcuts.section.imageSearchContext",
        (
            ("Enter", "shortcuts.imageSearch.openFirst", "shortcuts.imageSearch.openFirstDetail"),
            ("Esc", "shortcuts.imageSearch.clear", "shortcuts.imageSearch.clearDetail"),
        ),
    ),
    (
        "shortcuts.section.fileListContext",
        (
            ("Ctrl+A", "shortcuts.fileList.selectAll", "shortcuts.fileList.selectAllDetail"),
            ("Ctrl+Space", "shortcuts.fileList.toggle", "shortcuts.fileList.toggleDetail"),
            ("Enter", "shortcuts.fileList.open", "shortcuts.fileList.openDetail"),
            ("F2", "shortcuts.fileList.rename", "shortcuts.fileList.renameDetail"),
            ("Delete", "shortcuts.fileList.delete", "shortcuts.fileList.deleteDetail"),
        ),
    ),
    (
        "shortcuts.section.annotationListContext",
        (
            ("shortcuts.keys.riskMarker", "shortcuts.annotationList.nearDuplicate", "shortcuts.annotationList.nearDuplicateDetail"),
            ("Ctrl+A", "shortcuts.annotationList.selectAll", "shortcuts.annotationList.selectAllDetail"),
            ("shortcuts.keys.arrows", "shortcuts.annotationList.focus", "shortcuts.annotationList.focusDetail"),
            ("shortcuts.keys.shiftArrows", "shortcuts.annotationList.extend", "shortcuts.annotationList.extendDetail"),
            ("Space", "shortcuts.annotationList.select", "shortcuts.annotationList.selectDetail"),
            ("F2", "shortcuts.annotationList.edit", "shortcuts.annotationList.editDetail"),
            ("Esc", "shortcuts.annotationList.group", "shortcuts.annotationList.groupDetail"),
        ),
    ),
    (
        "shortcuts.section.cropContext",
        (
            ("shortcuts.keys.contextMenu", "shortcuts.crop.contextMenu", "shortcuts.crop.contextMenuDetail"),
            ("Ctrl+Z", "shortcuts.crop.undo", "shortcuts.crop.undoDetail"),
            ("shortcuts.keys.redo", "shortcuts.crop.redo", "shortcuts.crop.redoDetail"),
            ("Enter", "shortcuts.crop.apply", "shortcuts.crop.applyDetail"),
            ("Esc", "shortcuts.crop.cancel", "shortcuts.crop.cancelDetail"),
            ("shortcuts.keys.arrowsShift", "shortcuts.crop.move", "shortcuts.crop.moveDetail"),
        ),
    ),
    (
        "shortcuts.section.imageToolsContext",
        (
            ("Ctrl+Z", "shortcuts.imageTools.undo", "shortcuts.imageTools.undoDetail"),
            ("shortcuts.keys.redo", "shortcuts.imageTools.redo", "shortcuts.imageTools.redoDetail"),
        ),
    ),
)


def _resolve_action(window, name):
    action = getattr(getattr(window, "actions", None), name, None)
    if action is not None:
        return action
    return {
        "displayLabel": getattr(window, "display_label_option", None),
        "drawSquares": getattr(window, "draw_squares_option", None),
    }.get(name)


def _shortcut_texts(action):
    values = []
    for sequence in action.shortcuts():
        value = sequence.toString(QKeySequence.NativeText).strip()
        if value and value not in values:
            values.append(value)
    if not values:
        _label, separator, manual = str(action.text() or "").partition("\t")
        if separator and manual.strip():
            values.append(manual.strip())
    return tuple(values)


def _action_row(action):
    shortcuts = _shortcut_texts(action)
    if not shortcuts:
        return None
    return ShortcutRow(
        action=plain_action_text(action.text()),
        keys=" / ".join(shortcuts),
        explanation=str(action.statusTip() or plain_action_text(action.text())),
    )


def _native_context_keys(value):
    if value.startswith("shortcuts."):
        return tr(value)
    return " / ".join(
        QKeySequence(part.strip()).toString(QKeySequence.NativeText)
        or part.strip()
        for part in value.split(" / ")
    )


def build_shortcut_sections(window):
    """Combine live QAction bindings with explicit contextual interactions."""

    sections = []
    seen = set()
    for title_id, names in _ACTION_SECTIONS:
        rows = []
        for name in names:
            action = _resolve_action(window, name)
            if not isinstance(action, QAction) or id(action) in seen:
                continue
            row = _action_row(action)
            if row is None:
                continue
            seen.add(id(action))
            rows.append(row)
        if rows:
            sections.append(ShortcutSection(tr(title_id), tuple(rows)))

    other_rows = []
    for action in window.findChildren(QAction):
        if id(action) in seen or action.isSeparator():
            continue
        row = _action_row(action)
        if row is None:
            continue
        seen.add(id(action))
        other_rows.append(row)
    if other_rows:
        other_rows.sort(key=lambda row: (row.action.casefold(), row.keys))
        sections.append(ShortcutSection(
            tr("shortcuts.section.otherCommands"),
            tuple(other_rows),
        ))

    for title_id, definitions in _CONTEXT_SECTIONS:
        rows = tuple(
            ShortcutRow(
                action=tr(action_id),
                keys=_native_context_keys(keys),
                explanation=tr(explanation_id),
            )
            for keys, action_id, explanation_id in definitions
        )
        sections.append(ShortcutSection(tr(title_id), rows))
    return tuple(sections)


class ShortcutCatalogDialog(QDialog):
    """Scrollable catalog of live and context-specific keyboard commands."""

    def __init__(self, window):
        super().__init__(window)
        self.setObjectName("shortcutCatalogDialog")
        self.setWindowTitle(tr("shortcuts.title"))
        self.resize(920, 620)

        layout = QVBoxLayout(self)
        intro = QLabel(tr("shortcuts.intro"), self)
        intro.setObjectName("shortcutCatalogIntro")
        intro.setWordWrap(True)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText(tr("ui.shortcuts.search"))
        self.search.setAccessibleName(tr("ui.shortcuts.search"))
        self.search.setToolTip(intro.text())
        layout.addWidget(self.search)

        self.tree = QTreeWidget(self)
        self.tree.setObjectName("shortcutCatalogTree")
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels((
            tr("shortcuts.column.action"),
            tr("shortcuts.column.keys"),
            tr("shortcuts.column.explanation"),
        ))
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setWordWrap(True)
        self.tree.setAllColumnsShowFocus(True)
        self.sections = build_shortcut_sections(window)
        for section in self.sections:
            group = QTreeWidgetItem((section.title, "", ""))
            group.setFlags(group.flags() & ~Qt.ItemIsSelectable)
            font = group.font(0)
            font.setBold(True)
            group.setFont(0, font)
            self.tree.addTopLevelItem(group)
            self.tree.setFirstItemColumnSpanned(group, True)
            for row in section.rows:
                group.addChild(QTreeWidgetItem((
                    row.action,
                    row.keys,
                    row.explanation,
                )))
            group.setExpanded(True)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.tree, 1)
        self.search.textChanged.connect(self._filter)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.setObjectName("shortcutCatalogButtons")
        localize_dialog_buttons(buttons)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        present_dialog(self, scroll=True, icon="keyboard-shortcuts")

    def _filter(self, text):
        query = text.strip().casefold()
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            group_matches = query in group.text(0).casefold()
            shown = 0
            for row in range(group.childCount()):
                item = group.child(row)
                matches = group_matches or any(query in item.text(column).casefold() for column in range(3))
                item.setHidden(not matches)
                shown += matches
            group.setHidden(not shown)


class AboutDialog(QDialog):
    """Application identity and canonical repository link."""

    def __init__(self, name, version, python_version, parent=None):
        super().__init__(parent)
        self.setObjectName("aboutDialog")
        self.setWindowTitle(tr("info.title"))
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        brand = QFrame(self)
        brand.setObjectName("aboutIdentity")
        identity = QHBoxLayout(brand)
        identity.setContentsMargins(18, 18, 18, 18)
        identity.setSpacing(16)
        identity.addWidget(IconLabel("app", size=72))
        names = QVBoxLayout()
        names.setSpacing(7)
        name_label = QLabel(str(name))
        name_label.setTextFormat(Qt.PlainText)
        name_label.setObjectName("aboutProductName")
        names.addWidget(name_label)
        names.addWidget(role(QLabel(tr("ui.about.tagline")), "supporting"))
        release = QLabel("v" + str(version))
        release.setObjectName("aboutVersion")
        names.addWidget(release, 0, Qt.AlignLeft)
        identity.addLayout(names, 1)
        layout.addWidget(brand)

        runtime = QFrame(self)
        runtime.setObjectName("aboutRuntime")
        environment = QHBoxLayout(runtime)
        environment.setContentsMargins(14, 12, 14, 12)
        environment.addWidget(role(QLabel(tr("ui.about.environment")), "supporting"))
        values = QLabel(f"Python {python_version}  ·  Qt {QT_VERSION_STR}")
        values.setTextInteractionFlags(Qt.TextSelectableByMouse)
        environment.addWidget(values, 1, Qt.AlignRight)
        layout.addWidget(runtime)

        self.repository_button = QPushButton(tr("ui.about.repository"))
        self.repository_button.setObjectName("aboutRepository")
        self.repository_button.setIcon(new_icon("external-link"))
        self.repository_button.setToolTip(REPOSITORY_URL)
        self.repository_button.clicked.connect(self._open_repository)
        layout.addWidget(self.repository_button)
        apply_theme_style(self, theme_style("""
            QFrame#aboutIdentity { background: ${selected}; border: 1px solid ${accent_border}; border-radius: 10px; }
            QLabel#aboutProductName { color: ${text}; font-size: 20px; font-weight: 600; }
            QLabel#aboutVersion { color: ${accent}; background: ${selected}; padding: 3px 8px;
                border-radius: 6px; font-size: 11px; }
            QFrame#aboutRuntime { background: ${background}; border: none; border-radius: 7px; }
            QPushButton#aboutRepository { min-height: 38px; text-align: left; background: ${surface};
                border: 1px solid ${border}; border-radius: 7px; padding: 0 14px; color: ${text}; }
            QPushButton#aboutRepository:hover { background: ${background}; border-color: ${accent_border}; }
        """))

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.setObjectName("aboutButtons")
        localize_dialog_buttons(buttons)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        present_dialog(self, minimum_width=520, title=False)

    def _open_repository(self):
        QDesktopServices.openUrl(QUrl(REPOSITORY_URL))


__all__ = (
    "AboutDialog",
    "REPOSITORY_URL",
    "ShortcutCatalogDialog",
    "ShortcutRow",
    "ShortcutSection",
    "build_shortcut_sections",
)
