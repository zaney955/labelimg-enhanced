"""All appearance combinations are readable and preserve settings/data semantics."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QPalette
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.platform.settings import Settings
from labelimg.platform.settings_keys import SETTING_ACCENT_COLOR, SETTING_COLOR_MODE
from labelimg.ui.appearance import AppearanceController, AppearanceDialog
from labelimg.ui.theme import (
    COLORS,
    LIGHT_THEME,
    appearance_theme,
    current_theme,
    set_theme,
)
from labelimg.ui.theme_palettes import (
    available_accents,
    contrast_ratio,
)


class AppearanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from labelimg.ui.icons import install_icon_style
        from labelimg.ui.presentation import install_application_theme

        install_icon_style()
        install_application_theme()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ, {"LABELIMG_CONFIG_DIR": self.temporary.name}
        )
        self.environment.start()
        self.widgets = []
        self.settings = Settings()
        self.system = {"mode": "light"}
        self.controller = AppearanceController(
            self.settings, system_probe=lambda: self.system["mode"]
        )

    def tearDown(self):
        for widget in self.widgets:
            if hasattr(widget, "shutdown_image_decode_cache"):
                widget.stop_directory_load()
                widget.shutdown_image_decode_cache()
            widget.deleteLater()
        self.controller.timer.stop()
        self.controller.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()
        set_theme(LIGHT_THEME.identifier)
        set_language(ENGLISH)

    def test_every_mode_accent_has_readable_text_states_and_indicators(self):
        for mode in ("light", "dark"):
            for preset in available_accents():
                with self.subTest(mode=mode, accent=preset.identifier):
                    c = appearance_theme(mode, preset.identifier).colors
                    pairs = [
                        (fg, bg, 4.5)
                        for fg in ("text", "muted")
                        for bg in (
                            "surface",
                            "background",
                            "selected",
                            "canvas_verified",
                            "canvas_questioned",
                        )
                    ]
                    pairs += [
                        (fg, bg, 4.5)
                        for fg in ("accent", "accent_hover", "danger", "warning")
                        for bg in ("surface", "background")
                    ]
                    pairs += [
                        ("accent", "selected", 4.5),
                        ("accent_hover", "selected", 4.5),
                    ]
                    pairs += [
                        ("on_accent", bg, 4.5) for bg in ("accent", "accent_hover")
                    ]
                    pairs += [("border", bg, 3.0) for bg in ("surface", "background")]
                    pairs += [
                        ("accent_border", "selected", 3.0),
                        ("disabled_text", "disabled_background", 4.5),
                    ]
                    pairs += [
                        (role, role + "_tint", 3.0)
                        for role in (
                            "icon_file",
                            "icon_image",
                            "icon_success",
                            "icon_view",
                            "icon_preference",
                        )
                    ]
                    for fg, bg, minimum in pairs:
                        self.assertGreaterEqual(
                            contrast_ratio(c[fg], c[bg]),
                            minimum,
                            (mode, preset.identifier, fg, bg),
                        )
                    if mode == "dark":
                        self.assertNotEqual(c["accent"], preset.color)

    def test_system_changes_follow_only_while_system_is_selected(self):
        self.controller.apply_preferences("system", "rose")
        self.assertTrue(self.controller.timer.isActive())
        self.assertEqual(self.controller.effective_mode, "light")
        self.system["mode"] = "dark"
        self.controller.refresh_system()
        self.assertEqual(self.controller.effective_mode, "dark")
        self.assertEqual(self.controller.accent, "rose")
        self.assertEqual(current_theme().identifier, "appearance-dark-rose")
        self.controller.apply_preferences("light", "rose")
        self.assertFalse(self.controller.timer.isActive())
        self.controller.refresh_system()
        self.assertEqual(self.controller.effective_mode, "light")

    def test_mode_and_accent_save_together_and_restore_on_restart(self):
        self.settings["unrelated"] = "keep"
        self.controller.apply_preferences("dark", "teal", persist=True)
        reloaded = Settings()
        self.assertTrue(reloaded.load())
        self.assertEqual(reloaded.get(SETTING_COLOR_MODE), "dark")
        self.assertEqual(reloaded.get(SETTING_ACCENT_COLOR), "teal")
        self.assertEqual(reloaded.get("unrelated"), "keep")
        second = AppearanceController(reloaded)
        self.addCleanup(second.deleteLater)
        self.assertEqual(
            (second.mode, second.accent, second.effective_mode),
            ("dark", "teal", "dark"),
        )

    def dialog(self):
        dialog = AppearanceDialog(self.controller)
        self.widgets.append(dialog)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_preview_cancel_restores_mode_accent_without_writing_settings(self):
        self.settings["unrelated"] = "keep"
        self.settings.save()
        before = Path(self.settings.path).read_bytes()
        dialog = self.dialog()
        dialog.mode_buttons["dark"].click()
        dialog.accent_buttons["blue"].click()
        self.assertEqual(
            (self.controller.mode, self.controller.accent), ("dark", "blue")
        )
        self.assertEqual(current_theme().identifier, "appearance-dark-blue")
        QTest.keyClick(dialog, Qt.Key_Escape)
        self.assertEqual(
            (self.controller.mode, self.controller.accent), ("light", "plum")
        )
        self.assertEqual(Path(self.settings.path).read_bytes(), before)

    def test_settings_are_compact_and_have_no_sample_preview_controls(self):
        from PyQt5.QtWidgets import QLineEdit, QCheckBox

        dialog = self.dialog()
        self.assertFalse(dialog.findChildren(QLineEdit))
        self.assertFalse(dialog.findChildren(QCheckBox))
        self.assertLess(dialog.height(), 400)
        self.assertEqual(
            sum(button.isChecked() for button in dialog.accent_buttons.values()), 1
        )
        self.assertEqual(
            sum(button.isChecked() for button in dialog.mode_buttons.values()), 1
        )

    def test_accept_persists_both_selections(self):
        dialog = self.dialog()
        dialog.mode_buttons["system"].click()
        dialog.accent_buttons["green"].click()
        dialog.accept()
        restored = Settings()
        restored.load()
        self.assertEqual(restored.get(SETTING_COLOR_MODE), "system")
        self.assertEqual(restored.get(SETTING_ACCENT_COLOR), "green")

    def test_focus_on_another_mode_does_not_paint_a_second_selected_surface(self):
        from PyQt5.QtGui import QColor
        self.controller.apply_preferences('dark', 'plum')
        dialog = self.dialog()
        selected = dialog.mode_buttons['dark']
        focused = dialog.mode_buttons['system']
        focused.setFocus(Qt.TabFocusReason)
        self.app.processEvents()
        self.assertTrue(focused.hasFocus())
        self.assertFalse(focused.isChecked())
        self.assertTrue(selected.isChecked())
        def fill(button):
            pixels = button.grab().toImage()
            return pixels.pixelColor(pixels.width() // 2, pixels.height() - 8)
        self.assertEqual(fill(selected), QColor(COLORS['selected']))
        self.assertNotEqual(fill(focused), QColor(COLORS['selected']))
        before = selected.geometry()
        QTest.keyClick(focused, Qt.Key_Space)
        self.assertEqual(self.controller.mode, 'system')
        self.assertEqual(sum(button.isChecked() for button in dialog.mode_buttons.values()), 1)
        self.assertEqual(selected.geometry(), before)

    def test_cancel_system_preview_resolves_the_latest_system_mode(self):
        self.controller.apply_preferences("system", "amber")
        dialog = self.dialog()
        dialog.mode_buttons["light"].click()
        self.system["mode"] = "dark"
        dialog.reject()
        self.assertEqual(
            (
                self.controller.mode,
                self.controller.accent,
                self.controller.effective_mode,
            ),
            ("system", "amber", "dark"),
        )

    def test_bilingual_copy_and_palette_switch_keep_selection(self):
        dialog = self.dialog()
        set_language(SIMPLIFIED_CHINESE)
        self.assertEqual(dialog.mode_buttons["system"].text(), "跟随系统")
        self.assertEqual(dialog.accent_buttons["blue"].text(), "蓝色")
        dialog.mode_buttons["dark"].click()
        self.assertEqual(
            dialog.mode_caption.palette().color(QPalette.WindowText).name(),
            COLORS["text"].lower(),
        )
        set_language(ENGLISH)
        self.assertEqual(dialog.mode_buttons["system"].text(), "System")
        self.assertEqual(dialog.accent_buttons["blue"].text(), "Blue")
        dialog.reject()

    def test_invalid_preferences_fall_back_and_invalid_changes_are_atomic(self):
        bad = Settings()
        bad[SETTING_COLOR_MODE] = "bad"
        bad[SETTING_ACCENT_COLOR] = "missing"
        controller = AppearanceController(bad)
        self.addCleanup(controller.deleteLater)
        self.assertEqual((controller.mode, controller.accent), ("light", "plum"))
        before = current_theme()
        with self.assertRaises(ValueError):
            self.controller.apply_preferences("dark", "missing", persist=True)
        self.assertIs(current_theme(), before)
        self.assertNotIn(SETTING_COLOR_MODE, self.settings.data)

    def test_dark_startup_before_first_show_refreshes_inherited_chrome(self):
        from PyQt5.QtWidgets import QToolBar
        from PyQt5.QtGui import QColor
        from labelimg.workbench.bootstrap import (
            create_workbench,
            WorkbenchLaunchOptions,
        )

        self.controller.apply_preferences("dark", "rose", persist=True)
        set_theme(LIGHT_THEME.identifier)
        classes = Path(self.temporary.name) / "classes.txt"
        classes.write_text("", encoding="utf-8")
        window = create_workbench(WorkbenchLaunchOptions(class_file=str(classes)))
        self.widgets.append(window)
        window.show()
        self.app.processEvents()
        for widget in [*window.findChildren(QToolBar), window.statusBar()]:
            image = widget.grab().toImage()
            # The far-right status-bar position now contains the magnifier.
            # Sample its empty left margin rather than an icon/hover surface.
            sample_x = 2 if widget is window.statusBar() else image.width() - 25
            self.assertEqual(
                image.pixelColor(sample_x, image.height() // 2),
                QColor(COLORS["panel_header"] if widget.objectName() == "canvasToolRail" or widget is window.statusBar() else COLORS["surface"]),
            )
        window.zoom_widget.setEnabled(True)
        pixels = window.zoom_widget.slider.grab().toImage()
        self.assertIn(
            QColor(COLORS["accent"]).rgba(),
            {
                pixels.pixel(x, y)
                for x in range(pixels.width())
                for y in range(pixels.height())
            },
        )

    def test_application_closes_cleanly_in_every_mode(self):
        # Regression: a Python QIconEngine used to access freed Qt/Python state
        # after all assertions passed and QApplication was being destroyed.
        for mode in ("light", "dark", "system"):
            code = (
                "from PyQt5.QtCore import QTimer; "
                "from labelimg.workbench.bootstrap import get_main_app; "
                "a,w=get_main_app(); w.appearance.apply_preferences("
                + repr(mode)
                + ',"blue"); QTimer.singleShot(0,w.close); raise SystemExit(a.exec_())'
            )
            env = os.environ.copy()
            env["QT_QPA_PLATFORM"] = "offscreen"
            result = subprocess.run(
                [sys.executable, "-X", "faulthandler", "-B", "-c", code],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
