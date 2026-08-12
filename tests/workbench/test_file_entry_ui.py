import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent
from PyQt5.QtGui import QKeySequence
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QApplication, QDialog, QToolButton

from labelimg.workbench.main_window import MainWindow
from labelimg.localization.runtime import ENGLISH, set_language


class FileEntryUiTest(unittest.TestCase):
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
        self.window = MainWindow(
            default_prefdef_class_file=classes_path,
            default_save_dir="",
        )

    def tearDown(self):
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()
        set_language(ENGLISH)

    def test_top_bar_has_one_primary_open_directory_split_button(self):
        buttons = self.window.top_commands.findChildren(QToolButton)
        open_buttons = [
            button
            for button in buttons
            if button.defaultAction() in {
                self.window.actions.open,
                self.window.actions.openDir,
                self.window.actions.changeSaveDir,
                self.window.actions.replaceAnnotation,
            }
        ]

        self.assertEqual(len(open_buttons), 1)
        button = open_buttons[0]
        self.assertIs(button.defaultAction(), self.window.actions.openDir)
        self.assertEqual(button.popupMode(), QToolButton.MenuButtonPopup)
        self.assertIsNotNone(button.menu())
        self.assertEqual(
            button.menu().actions(),
            [self.window.actions.open],
        )

    def test_file_entry_actions_have_distinct_semantics_and_shortcuts(self):
        actions = (
            self.window.actions.openDir,
            self.window.actions.open,
            self.window.actions.changeSaveDir,
            self.window.actions.replaceAnnotation,
        )

        self.assertEqual(
            [action.text() for action in actions],
            [
                "Open Image Directory…",
                "Open File…",
                "Choose Annotation Directory…",
                "Replace Current Annotations…",
            ],
        )
        self.assertEqual(
            self.window.actions.open.shortcut(),
            QKeySequence("Ctrl+O"),
        )
        self.assertEqual(
            self.window.actions.openDir.shortcut(),
            QKeySequence("Ctrl+Shift+O"),
        )
        self.assertTrue(self.window.actions.changeSaveDir.shortcut().isEmpty())
        self.assertTrue(self.window.actions.replaceAnnotation.shortcut().isEmpty())
        self.assertTrue(all(not action.icon().isNull() for action in actions))
        self.assertEqual(
            len({action.icon().cacheKey() for action in actions}),
            len(actions),
        )

    def test_file_menu_separates_open_workspace_and_annotation_commands(self):
        actions = self.window.menus.file.actions()

        self.assertEqual(
            actions[:10],
            [
                self.window.actions.openDir,
                self.window.actions.open,
                self.window.menus.recentFiles.menuAction(),
                actions[3],
                self.window.menus.annotationDirectory.menuAction(),
                actions[5],
                self.window.actions.replaceAnnotation,
                self.window.actions.save,
                self.window.actions.saveAs,
                self.window.actions.save_format,
            ],
        )
        self.assertTrue(actions[3].isSeparator())
        self.assertTrue(actions[5].isSeparator())
        annotation_actions = self.window.menus.annotationDirectory.actions()
        self.assertEqual(
            [action.text() for action in annotation_actions],
            [
                "Current: Same as Image Directory",
                "",
                "Choose Annotation Directory…",
                "Use Image Directory",
            ],
        )
        self.assertFalse(annotation_actions[0].isEnabled())
        self.assertTrue(annotation_actions[1].isSeparator())

    def test_annotation_directory_status_tracks_choose_and_restore(self):
        self.assertEqual(
            self.window.annotation_directory_label.text(),
            "Annotation Directory: Same as Image Directory",
        )
        self.assertFalse(self.window.actions.useImageDirectory.isEnabled())

        annotation_dir = os.path.join(self.temporary.name, "labels")
        os.makedirs(annotation_dir)
        with patch(
            "labelimg.workbench.main_window.QFileDialog.getExistingDirectory",
            return_value=annotation_dir,
        ):
            self.window.actions.changeSaveDir.trigger()

        self.assertEqual(
            self.window.annotation_directory_label.text(),
            "Annotation Directory: labels",
        )
        self.assertEqual(
            self.window.annotation_directory_label.toolTip(),
            os.path.abspath(annotation_dir),
        )
        self.assertEqual(
            self.window.actions.annotationDirectoryCurrent.text(),
            "Current: labels",
        )
        self.assertTrue(self.window.actions.useImageDirectory.isEnabled())

        self.window.actions.useImageDirectory.trigger()

        self.assertIsNone(self.window.default_save_dir)
        self.assertEqual(
            self.window.annotation_directory_label.text(),
            "Annotation Directory: Same as Image Directory",
        )
        self.assertEqual(
            self.window.actions.annotationDirectoryCurrent.text(),
            "Current: Same as Image Directory",
        )
        self.assertFalse(self.window.actions.useImageDirectory.isEnabled())

        image_path = os.path.join(self.temporary.name, "workspace.png")
        image = QImage(20, 20, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(image_path))
        self.window.import_dir_images(self.temporary.name)

        self.assertEqual(
            self.window.annotation_directory_label.toolTip(),
            os.path.abspath(self.temporary.name),
        )

    def test_replace_annotations_preserves_unsaved_work_when_user_cancels(self):
        image_path = os.path.join(self.temporary.name, "sample.png")
        image = QImage(40, 40, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(image_path))
        self.assertTrue(self.window.load_file(image_path))
        self.window.annotation_clipboard = [
            (
                "cat",
                ((5, 5), (20, 5), (20, 20), (5, 20)),
                None,
                None,
                False,
            ),
        ]
        self.window.actions.pasteAnnotations.trigger()
        self.assertEqual(
            [shape.label for shape in self.window.canvas.shapes],
            ["cat"],
        )

        with patch(
            "labelimg.workbench.main_window.QDialog.exec_",
            return_value=QDialog.Rejected,
        ), patch(
            "labelimg.workbench.main_window.QFileDialog.getOpenFileName",
        ) as file_picker:
            self.window.actions.replaceAnnotation.trigger()

        file_picker.assert_not_called()
        self.assertEqual(
            [shape.label for shape in self.window.canvas.shapes],
            ["cat"],
        )


if __name__ == "__main__":
    unittest.main()
