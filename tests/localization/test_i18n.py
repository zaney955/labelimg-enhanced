import os
import ast
from pathlib import Path
import re
import string
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from labelimg.workbench.main_window import MainWindow
from labelimg.platform.settings_keys import SETTING_LANGUAGE
from labelimg.localization.runtime import (
    ENGLISH,
    SIMPLIFIED_CHINESE,
    localize_dialog_buttons,
    localize_message_box_buttons,
    normalize_language,
    set_language,
    system_language,
    tr,
)
from labelimg.platform.settings import Settings
from labelimg.localization.catalogs import CATALOGS


class TranslationCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        set_language(ENGLISH)

    def test_catalogs_have_identical_keys_and_format_fields(self):
        english = CATALOGS[ENGLISH]
        chinese = CATALOGS[SIMPLIFIED_CHINESE]
        self.assertEqual(set(english), set(chinese))
        formatter = string.Formatter()
        localized_template_tokens = {
            "renameBatch.defaultTemplate",
            "renameBatch.help",
        }
        for message_id in english:
            if message_id in localized_template_tokens:
                continue
            english_fields = {
                field
                for _literal, field, _spec, _conversion
                in formatter.parse(english[message_id])
                if field is not None
            }
            chinese_fields = {
                field
                for _literal, field, _spec, _conversion
                in formatter.parse(chinese[message_id])
                if field is not None
            }
            self.assertEqual(
                english_fields,
                chinese_fields,
                message_id,
            )

    def test_every_chinese_locale_maps_to_simplified_chinese(self):
        for locale_name in ("zh", "zh-CN", "zh_TW", "zh-Hant-HK"):
            self.assertEqual(
                normalize_language(locale_name),
                SIMPLIFIED_CHINESE,
            )
        for locale_name in ("en_US", "ja_JP", "de-DE", "UTF-8", None):
            self.assertEqual(normalize_language(locale_name), ENGLISH)

    def test_first_launch_uses_system_locale_mapping(self):
        with patch("labelimg.localization.runtime.locale.getlocale", return_value=("zh_TW", "UTF-8")):
            self.assertEqual(system_language(), SIMPLIFIED_CHINESE)
        with patch("labelimg.localization.runtime.locale.getlocale", return_value=("ja_JP", "UTF-8")):
            self.assertEqual(system_language(), ENGLISH)

    def test_translation_falls_back_to_the_selected_complete_catalog(self):
        set_language(ENGLISH)
        self.assertEqual(tr("menu_view"), "&View")
        set_language(SIMPLIFIED_CHINESE)
        self.assertEqual(tr("menu_view"), "视图(&V)")
        with self.assertRaises(KeyError):
            tr("missing.message")

    def test_qt_standard_buttons_follow_application_language(self):
        application = self.app
        set_language(SIMPLIFIED_CHINESE)
        chinese = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        localize_dialog_buttons(chinese)
        self.assertEqual(
            chinese.button(QDialogButtonBox.Ok).text(),
            "确定",
        )
        self.assertEqual(
            chinese.button(QDialogButtonBox.Cancel).text(),
            "取消",
        )
        message_box = QMessageBox()
        message_box.setStandardButtons(
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
        )
        localize_message_box_buttons(message_box)
        self.assertEqual(message_box.button(QMessageBox.Yes).text(), "是(&Y)")
        self.assertEqual(message_box.button(QMessageBox.No).text(), "否(&N)")
        self.assertEqual(message_box.button(QMessageBox.Cancel).text(), "取消")
        set_language(ENGLISH)
        english = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        localize_dialog_buttons(english)
        self.assertEqual(english.button(QDialogButtonBox.Ok).text(), "OK")
        self.assertEqual(
            english.button(QDialogButtonBox.Cancel).text(),
            "Cancel",
        )
        chinese.deleteLater()
        english.deleteLater()
        message_box.deleteLater()
        application.processEvents()

    def test_every_static_translation_reference_exists(self):
        source_root = Path(__file__).resolve().parents[1] / "src" / "labelimg"
        referenced = set()
        for source_path in source_root.rglob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Name) or node.func.id != "tr":
                    continue
                if node.args and isinstance(node.args[0], ast.Constant):
                    referenced.add(node.args[0].value)
        self.assertEqual(
            referenced - set(CATALOGS[ENGLISH]),
            set(),
        )

    def test_ui_calls_do_not_embed_application_language_text(self):
        source_root = Path(__file__).resolve().parents[1] / "src" / "labelimg"
        ui_calls = {
            "QAction", "QCheckBox", "QLabel", "QProgressDialog",
            "QPushButton", "addAction", "addItems", "addMenu",
            "critical", "error_message", "getExistingDirectory",
            "getItem", "getOpenFileName", "getText", "information",
            "question", "setHorizontalHeaderLabels", "setInformativeText",
            "setPlaceholderText", "setStatusTip", "setText", "setToolTip",
            "setWhatsThis", "setWindowTitle", "showMessage", "status",
            "warning",
        }
        failures = []
        for source_path in source_root.rglob("*.py"):
            if source_path.name in {"i18n.py", "translations.py"}:
                continue
            source = source_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                name = (
                    function.id
                    if isinstance(function, ast.Name)
                    else function.attr
                    if isinstance(function, ast.Attribute)
                    else ""
                )
                if name not in ui_calls:
                    continue
                segment = ast.get_source_segment(source, node) or ""
                if "tr(" in segment:
                    continue
                constants = [
                    child.value
                    for child in ast.walk(node)
                    if isinstance(child, ast.Constant)
                    and isinstance(child.value, str)
                ]
                visible = [
                    value
                    for value in constants
                    if re.search(r"[A-Za-z]{3,}|[\u4e00-\u9fff]", value)
                ]
                if visible:
                    failures.append(
                        "%s:%d: %s" % (
                            source_path.name,
                            node.lineno,
                            visible,
                        )
                    )
        self.assertEqual(failures, [])


class RuntimeLanguageSwitchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
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
        )

    def tearDown(self):
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()
        set_language(ENGLISH)

    def test_switch_updates_visible_main_window_text_and_persists(self):
        self.window.change_language(SIMPLIFIED_CHINESE)
        self.assertEqual(self.window.menus.view.title(), "视图(&V)")
        self.assertEqual(self.window.menus.settings.title(), "设置(&S)")
        self.assertEqual(self.window.actions.labels.text(), "标注面板")
        self.assertEqual(
            self.window.actions.showInfo.text(),
            "关于 LabelImg Enhanced",
        )
        self.assertEqual(
            self.window.file_list_empty_label.text(),
            "没有符合筛选条件的文件",
        )
        self.assertEqual(
            self.window.language_actions[SIMPLIFIED_CHINESE].isChecked(),
            True,
        )
        settings = Settings()
        self.assertTrue(settings.load())
        self.assertEqual(settings[SETTING_LANGUAGE], SIMPLIFIED_CHINESE)

        self.window.change_language(ENGLISH)
        self.assertEqual(self.window.menus.view.title(), "&View")
        self.assertEqual(self.window.menus.settings.title(), "&Settings")
        self.assertEqual(
            self.window.file_list_empty_label.text(),
            "No files match the filters",
        )
        self.assertTrue(self.window.language_actions[ENGLISH].isChecked())


if __name__ == "__main__":
    unittest.main()
