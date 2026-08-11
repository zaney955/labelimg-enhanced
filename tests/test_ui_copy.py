import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication, QAction, QToolButton

from labelimg.app import MainWindow
from labelimg.i18n import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.translations import CATALOGS
from labelimg.utils import format_action_tooltip


class UserInterfaceCopyTest(unittest.TestCase):
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

    def test_command_tooltips_use_concise_titles_and_show_shortcuts(self):
        expected = {
            ENGLISH: {
                "rotate": "Rotate Right",
                "create": "Draw Box (W)",
                "questioned": "Needs Review (Ctrl+Space)",
                "verified": "Verified (Space)",
                "zoom_in": "Zoom In (Ctrl++)",
                "zoom_out": "Zoom Out (Ctrl+-)",
            },
            SIMPLIFIED_CHINESE: {
                "rotate": "向右旋转",
                "create": "绘制标注框（W）",
                "questioned": "待复核（Ctrl+Space）",
                "verified": "已验证（Space）",
                "zoom_in": "放大（Ctrl++）",
                "zoom_out": "缩小（Ctrl+-）",
            },
        }

        for language in (SIMPLIFIED_CHINESE, ENGLISH):
            self.window.change_language(language)
            copy = expected[language]
            self.assertEqual(
                self.window.top_commands.rotate_button.toolTip(),
                copy["rotate"],
            )
            self.assertEqual(
                self.window.tools.buttons["create"].toolTip(),
                copy["create"],
            )
            self.assertEqual(
                self.window.review_control.buttons["questioned"].toolTip(),
                copy["questioned"],
            )
            self.assertEqual(
                self.window.review_control.buttons["verified"].toolTip(),
                copy["verified"],
            )
            self.assertEqual(
                self.window.zoom_widget.plus.toolTip(),
                copy["zoom_in"],
            )
            self.assertEqual(
                self.window.zoom_widget.minus.toolTip(),
                copy["zoom_out"],
            )

            for name, action in vars(self.window.actions).items():
                if not isinstance(action, QAction):
                    continue
                self.assertEqual(
                    action.toolTip(),
                    format_action_tooltip(action.text(), action.shortcuts()),
                    "%s (%s)" % (name, language),
                )
                shortcut_texts = [
                    shortcut.toString()
                    for shortcut in action.shortcuts()
                    if not shortcut.isEmpty()
                ]
                for shortcut_text in shortcut_texts:
                    self.assertIn(
                        shortcut_text,
                        action.toolTip(),
                        "%s (%s)" % (name, language),
                    )
            for button in self.window.findChildren(QToolButton):
                action = button.defaultAction()
                if action is not None:
                    self.assertEqual(
                        button.toolTip(),
                        action.toolTip(),
                        "%s (%s)" % (button.objectName(), language),
                    )

        self.assertEqual(
            self.window.actions.rotateClockwise.statusTip(),
            "Rotate the current image and its annotations right by 90°",
        )

    def test_history_actions_retranslate_without_an_open_image(self):
        self.window.change_language(SIMPLIFIED_CHINESE)

        self.assertTrue(
            self.window.actions.undoAnnotation.text().startswith("撤销")
        )
        self.assertTrue(
            self.window.actions.redoAnnotation.text().startswith("重做")
        )

    def test_catalog_uses_consistent_object_names_and_action_semantics(self):
        chinese = CATALOGS[SIMPLIFIED_CHINESE]
        self.assertEqual(
            [
                (message_id, text)
                for message_id, text in chinese.items()
                if "图片" in text
            ],
            [],
        )
        self.assertEqual(
            CATALOGS[ENGLISH]["action.copyLabels"],
            "Copy Selected Annotations",
        )
        self.assertEqual(
            chinese["action.copyLabels"],
            "复制所选标注",
        )
        self.assertEqual(
            CATALOGS[ENGLISH]["imageTools.action.removeFrames"],
            "Remove Red/Yellow Borders…",
        )
        self.assertEqual(
            chinese["imageTools.action.removeFrames"],
            "去除红色/黄色边框…",
        )


if __name__ == "__main__":
    unittest.main()
