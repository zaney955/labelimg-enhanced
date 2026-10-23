"""Existing controls change theme without changing user data or command state."""

import ast
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPalette
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QLineEdit,
    QProgressDialog,
    QRadioButton,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
)

from labelimg.annotations.ui.candidate_label_dialog import CandidateLabelDialog
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.ui.presentation import install_application_theme, present_dialog
from labelimg.ui.icons import icon, install_icon_style
from labelimg.ui.theme import (
    COLORS,
    LIGHT_THEME,
    Theme,
    apply_theme_style,
    available_themes,
    current_theme,
    register_theme,
    set_theme,
    theme_style,
)
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench
from labelimg.workbench.help_ui import AboutDialog

TEST_THEME = LIGHT_THEME.with_overrides(
    "test-ocean",
    name_en="Test Ocean",
    name_zh="测试海蓝",
    accent="#306A87",
    accent_hover="#24536D",
    selected="#E8F2F7",
    accent_border="#B7D1DE",
    surface="#FCFDFE",
    text="#172F40",
)


class ThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        install_icon_style()
        install_application_theme()
        if TEST_THEME.identifier not in {t.identifier for t in available_themes()}:
            register_theme(TEST_THEME)

    def setUp(self):
        set_theme(LIGHT_THEME.identifier)
        self.widgets = []

    def tearDown(self):
        set_theme(LIGHT_THEME.identifier)
        for widget in self.widgets:
            if hasattr(widget, "shutdown_image_decode_cache"):
                widget.stop_directory_load()
                widget.shutdown_image_decode_cache()
            widget.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        set_language(ENGLISH)

    def test_registry_validates_complete_immutable_roles_before_switch(self):
        with self.assertRaises(ValueError):
            Theme("broken", "Broken", "错误", {"accent": "blue"})
        with self.assertRaises(ValueError):
            LIGHT_THEME.with_overrides(
                "bad", name_en="Bad", name_zh="错误", accent="blue"
            )
        with self.assertRaises(TypeError):
            TEST_THEME.colors["accent"] = "#000000"
        with self.assertRaises(ValueError):
            register_theme(TEST_THEME)
        with self.assertRaises(KeyError):
            set_theme("does-not-exist")
        self.assertEqual(current_theme(), LIGHT_THEME)

    def test_existing_dialog_preserves_input_selection_and_disabled_commit(self):
        dialog = QDialog()
        self.widgets.append(dialog)
        layout = QVBoxLayout(dialog)
        entry = QLineEdit("裂纹.keep.exact")
        entry.setSelection(3, 4)
        layout.addWidget(entry)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
        commit = buttons.button(QDialogButtonBox.Ok)
        commit.setEnabled(False)
        apply_theme_style(
            dialog, theme_style("QDialog { border: 1px solid ${accent}; }")
        )
        present_dialog(dialog, primary=commit)
        dialog.show()
        before = (entry.text(), entry.selectedText())
        set_theme(TEST_THEME.identifier)
        self.app.processEvents()
        self.assertEqual((entry.text(), entry.selectedText()), before)
        self.assertFalse(commit.isEnabled())
        self.assertIn(TEST_THEME.colors["accent"], dialog.styleSheet())
        self.assertNotIn(LIGHT_THEME.colors["accent"], dialog.styleSheet())
        self.assertEqual(
            entry.palette().color(QPalette.Highlight).name(), COLORS["selected"].lower()
        )

    def test_about_and_candidate_styles_remain_bound_across_repeated_switches(self):
        about = AboutDialog("LabelImg Enhanced", "2.6.0", "3.14.2")
        chooser = CandidateLabelDialog(list_item=["裂纹", "keep-user-name"])
        self.widgets += [about, chooser]
        chooser.edit.setText("keep-user-name")
        for language, theme in (
            (SIMPLIFIED_CHINESE, TEST_THEME),
            (ENGLISH, LIGHT_THEME),
            (ENGLISH, TEST_THEME),
        ):
            set_language(language)
            set_theme(theme.identifier)
            self.assertEqual(chooser.edit.text(), "keep-user-name")
            self.assertIn(theme.colors["accent"], about.styleSheet())
            self.assertIn(theme.colors["accent"], chooser.styleSheet())
        later = CandidateLabelDialog(list_item=["later"])
        self.widgets.append(later)
        self.assertIn(TEST_THEME.colors["accent"], later.styleSheet())
        self.assertNotIn(LIGHT_THEME.colors["accent"], later.styleSheet())

    def test_parentless_input_and_progress_dialogs_inherit_application_theme(self):
        set_theme(TEST_THEME.identifier)
        prompt = QInputDialog()
        progress = QProgressDialog("Scanning", "Cancel", 0, 100)
        self.widgets += [prompt, progress]
        prompt.setTextValue("unchanged")
        progress.setValue(27)
        for widget in self.widgets:
            widget.ensurePolished()
            self.assertEqual(
                widget.palette().color(QPalette.Highlight).name(),
                COLORS["selection_background"].lower(),
            )
            self.assertEqual(
                widget.palette().color(QPalette.Text).name(), COLORS["text"].lower()
            )
        set_theme(LIGHT_THEME.identifier)
        self.assertEqual(prompt.textValue(), "unchanged")
        self.assertEqual(progress.value(), 27)

    def test_choice_controls_paint_theme_states_and_keep_native_toggle_behavior(self):
        set_theme(TEST_THEME.identifier)
        for control_type, primitive in (
            (QCheckBox, QStyle.PE_IndicatorCheckBox),
            (QRadioButton, QStyle.PE_IndicatorRadioButton),
        ):
            widget = control_type("Choice")
            self.widgets.append(widget)
            widget.show()
            QTest.mouseClick(widget, Qt.LeftButton)
            self.assertTrue(widget.isChecked())

            option = QStyleOptionButton()
            option.initFrom(widget)
            option.rect.setRect(0, 0, 20, 20)
            option.state = QStyle.State_Enabled | QStyle.State_On
            image = QImage(20, 20, QImage.Format_ARGB32)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            widget.style().drawPrimitive(primitive, option, painter, widget)
            painter.end()
            self.assertIn(
                QColor(COLORS["accent"]).rgba(),
                {image.pixel(x, y) for x in range(20) for y in range(20)},
            )
            widget.setEnabled(False)
            QTest.mouseClick(widget, Qt.LeftButton)
            self.assertTrue(widget.isChecked())

    def test_preexisting_command_icon_repaints_with_current_theme(self):
        from PyQt5.QtWidgets import QToolButton

        button = QToolButton()
        self.widgets.append(button)
        button.setIcon(icon("annotation-panel"))
        first = button.icon().pixmap(32, 32).toImage()
        identity = icon("app").pixmap(32, 32).toImage()
        set_theme(TEST_THEME.identifier)
        self.assertNotEqual(first, button.icon().pixmap(32, 32).toImage())
        self.assertEqual(identity, icon("app").pixmap(32, 32).toImage())

    def test_workbench_switch_preserves_image_annotations_history_and_shortcuts(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"LABELIMG_CONFIG_DIR": directory}),
        ):
            classes = Path(directory) / "classes.txt"
            classes.write_text("", encoding="utf-8")
            path = Path(directory) / "image.png"
            image = QImage(80, 60, QImage.Format_RGB32)
            image.fill(QColor("#6A8642"))
            image.save(str(path))
            window = create_workbench(WorkbenchLaunchOptions(class_file=str(classes)))
            self.widgets.append(window)
            self.assertTrue(window.load_file(str(path)))
            window.auto_saving.setChecked(False)
            window.annotation_clipboard = [
                ("裂纹", ((5, 5), (35, 5), (35, 30), (5, 30)), False)
            ]
            window.paste_copied_bounding_boxes()
            shape = window.canvas.shapes[0]
            before = (
                shape.label,
                tuple((p.x(), p.y()) for p in shape.points),
                shape.line_color.rgba(),
                window.dirty,
                window.actions.openDir.shortcut().toString(),
            )
            before_image = window.canvas.pixmap.toImage()
            set_theme(TEST_THEME.identifier)
            self.app.processEvents()
            self.assertEqual(
                (
                    shape.label,
                    tuple((p.x(), p.y()) for p in shape.points),
                    shape.line_color.rgba(),
                    window.dirty,
                    window.actions.openDir.shortcut().toString(),
                ),
                before,
            )
            self.assertEqual(window.canvas.pixmap.toImage(), before_image)
            self.assertIn(COLORS["accent"], window.dock.styleSheet())
            window.undo_annotation()
            self.assertEqual(len(window.canvas.shapes), 0)

    def test_stylesheet_arrow_artwork_uses_the_current_semantic_palette(self):
        from labelimg.ui.theme import appearance_theme
        from labelimg.ui.icons import themed_icon_path

        dialog = QDialog()
        self.widgets.append(dialog)
        present_dialog(dialog)
        for mode in ("dark", "light"):
            set_theme(appearance_theme(mode, "teal").identifier)
            path = themed_icon_path("chevron-down")
            self.assertIn(path, dialog.styleSheet())
            from PyQt5.QtCore import QFile, QIODevice
            artwork = QFile(path)
            self.assertTrue(artwork.open(QIODevice.ReadOnly))
            self.assertIn(COLORS["icon_view"].encode(), bytes(artwork.readAll()))
            artwork.close()

    def test_ui_styles_cannot_bypass_the_color_interface(self):
        root = Path(__file__).resolve().parents[2] / "src/labelimg"
        violations = []
        for path in root.rglob("*.py"):
            if path.name in ("theme.py", "generated_resources.py"):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "setStyleSheet"
                ):
                    violations.append(f"{path.name}:{node.lineno} unbound QSS")
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and "{" in node.value
                    and re.search(r"(background|border|color)\s*:", node.value)
                    and re.search(r"#[\da-fA-F]{3,8}\b", node.value)
                ):
                    violations.append(f"{path.name}:{node.lineno} hardcoded QSS color")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
