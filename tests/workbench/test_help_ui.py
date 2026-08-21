import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QApplication, QDialog

from labelimg.localization.runtime import (
    ENGLISH,
    SIMPLIFIED_CHINESE,
    set_language,
)
from labelimg.ui.actions import plain_action_text
from labelimg.workbench.bootstrap import (
    WorkbenchLaunchOptions,
    create_workbench,
)
from labelimg.workbench.help_ui import (
    AboutDialog,
    REPOSITORY_URL,
    ShortcutCatalogDialog,
    build_shortcut_sections,
)


class HelpDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language(ENGLISH)
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {"LABELIMG_CONFIG_DIR": self.temporary.name},
        )
        self.environment.start()
        classes_path = os.path.join(self.temporary.name, "classes.txt")
        with open(classes_path, "w", encoding="utf-8"):
            pass
        self.window = create_workbench(WorkbenchLaunchOptions(
            class_file=classes_path,
            save_dir="",
        ))

    def tearDown(self):
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()
        set_language(ENGLISH)

    def test_catalog_reads_current_action_shortcuts_and_explanations(self):
        self.window.actions.save.setShortcut("Alt+S")

        rows = [
            row
            for section in build_shortcut_sections(self.window)
            for row in section.rows
        ]
        save = next(
            row
            for row in rows
            if row.action == plain_action_text(self.window.actions.save.text())
        )

        self.assertEqual(save.keys, "Alt+S")
        self.assertEqual(save.explanation, self.window.actions.save.statusTip())
        self.assertTrue(any(
            row.keys == QKeySequence("Delete").toString(
                QKeySequence.NativeText
            )
            and row.action == "Delete selected files"
            for row in rows
        ))
        self.assertTrue(any(
            row.keys == "Arrow keys / Shift+Arrow keys"
            and row.action == "Move crop region"
            for row in rows
        ))
        self.assertTrue(any(
            row.keys == "Left-button double-click"
            and row.action == "Edit box label"
            for row in rows
        ))
        self.assertTrue(any(
            row.keys == "Click overlap badge"
            and row.action == "Inspect near-duplicate boxes"
            for row in rows
        ))
        self.assertTrue(any(
            row.keys == "Click risk marker"
            and row.action == "Manage overlap finding"
            for row in rows
        ))
        self.assertEqual(
            self.window.actions.selectTool.statusTip(),
            "Select and edit annotations",
        )

    def test_shortcut_dialog_is_local_and_scrollable(self):
        dialog = ShortcutCatalogDialog(self.window)

        self.assertEqual(dialog.windowTitle(), "Keyboard Shortcuts")
        self.assertGreater(dialog.tree.topLevelItemCount(), 5)
        self.assertTrue(all(
            dialog.tree.topLevelItem(index).isExpanded()
            for index in range(dialog.tree.topLevelItemCount())
        ))
        with (
            patch(
                "labelimg.workbench.help_ui.ShortcutCatalogDialog.exec_",
                return_value=QDialog.Rejected,
            ),
            patch("labelimg.workbench.main_window.wb.open") as browser_open,
        ):
            self.window.show_shortcuts_dialog()
        browser_open.assert_not_called()
        dialog.deleteLater()

    def test_shortcut_dialog_uses_current_application_language(self):
        self.window.change_language(SIMPLIFIED_CHINESE)

        dialog = ShortcutCatalogDialog(self.window)

        self.assertEqual(dialog.windowTitle(), "键盘快捷键")
        self.assertEqual(dialog.tree.headerItem().text(0), "操作")
        canvas_section = next(
            section for section in dialog.sections
            if section.title == "画布上下文"
        )
        self.assertTrue(any(
            row.keys == "双击鼠标左键"
            and row.action == "修改标注标签"
            for row in canvas_section.rows
        ))
        self.assertTrue(any(
            row.keys == "点击重叠徽标"
            and row.action == "检查近重复标注框"
            for row in canvas_section.rows
        ))
        self.assertEqual(dialog.sections[-1].title, "图像工具对话框")
        dialog.deleteLater()

    def test_about_dialog_exposes_clickable_canonical_repository(self):
        dialog = AboutDialog("labelImg", "2.0.0", "3.14.0", self.window)

        self.assertIn(REPOSITORY_URL, dialog.information.text())
        self.assertTrue(dialog.information.openExternalLinks())
        self.assertTrue(
            dialog.information.textInteractionFlags()
            & Qt.LinksAccessibleByMouse
        )
        self.assertTrue(
            dialog.information.textInteractionFlags()
            & Qt.TextSelectableByMouse
        )
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
