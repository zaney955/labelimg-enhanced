"""Real dock layout, pointer gestures and content survive the shared panel shell."""

import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QHoverEvent, QImage, QPainter
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDockWidget, QStyle, QStyleOption, QToolButton
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.ui.panels import PanelHeader
from labelimg.ui.theme import COLORS, appearance_theme
from labelimg.ui.theme_palettes import available_accents, contrast_ratio
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class PanelChromeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font = Path("C:/Windows/Fonts/msyh.ttc")
        if font.is_file():
            fid = QFontDatabase.addApplicationFont(str(font))
            cls.app.setFont(QFont(QFontDatabase.applicationFontFamilies(fid)[0], 9))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"LABELIMG_CONFIG_DIR": self.temporary.name})
        self.env.start()
        classes = Path(self.temporary.name) / "classes.txt"
        classes.write_text("", encoding="utf-8")
        self.window = create_workbench(WorkbenchLaunchOptions(class_file=str(classes)))
        self.window.change_language(ENGLISH)
        self.window.resize(1400, 900)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.stop_directory_load()
        self.window.shutdown_image_decode_cache()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.env.stop()
        self.temporary.cleanup()
        set_language(ENGLISH)

    @property
    def docks(self):
        return (self.window.dock, self.window.file_dock, self.window.image_quality_dock)

    def test_docks_share_a_complete_header_without_clipping(self):
        self.window.image_quality_dock.show()
        self.app.processEvents()
        for dock in self.docks:
            header = dock.titleBarWidget()
            self.assertIsInstance(header, PanelHeader)
            self.assertEqual(header.height(), 38)
            self.assertEqual(dock.widget().property("uiRole"), "panelBody")
            self.assertEqual(dock.widget().y(), 38)
            for control in header.findChildren(QToolButton):
                self.assertTrue(
                    header.rect().contains(control.geometry()),
                    (dock.objectName(), control.geometry()),
                )
        self.assertEqual(
            self.window.file_list_controls.sort_button.property("uiRole"), "menuButton"
        )

    def test_workspace_gutters_are_resizable_visible_boundaries(self):
        center = self.window.centralWidget().geometry()
        annotation = self.window.dock.geometry()
        files = self.window.file_dock.geometry()
        self.assertEqual(annotation.left() - center.right() - 1, 6)
        self.assertEqual(files.top() - annotation.bottom() - 1, 6)
        point = QPoint(annotation.left() - 4, annotation.center().y())
        image = self.window.grab().toImage()
        self.assertEqual(image.pixelColor(point), QColor(COLORS["workspace_gutter"]))
        self.assertNotEqual(COLORS["workspace_gutter"], COLORS["surface"])
        self.app.sendEvent(
            self.window, QHoverEvent(QEvent.HoverMove, point, QPoint(-1, -1))
        )
        self.app.processEvents()
        self.assertEqual(
            self.window.grab().toImage().pixelColor(point),
            QColor(COLORS["accent_border"]),
        )
        option = QStyleOption()
        option.rect.setRect(0, 0, 8, 40)
        option.state = QStyle.State_Enabled | QStyle.State_MouseOver
        hover = QImage(8, 40, QImage.Format_ARGB32)
        hover.fill(Qt.transparent)
        painter = QPainter(hover)
        self.window.style().drawPrimitive(
            QStyle.PE_IndicatorDockWidgetResizeHandle, option, painter, self.window
        )
        painter.end()
        self.assertEqual(hover.pixelColor(4, 20), QColor(COLORS["accent_border"]))

    def test_all_panels_are_movable_floatable_and_keep_close_policy(self):
        for dock in self.docks:
            self.assertTrue(dock.features() & QDockWidget.DockWidgetMovable)
            self.assertTrue(dock.features() & QDockWidget.DockWidgetFloatable)
        self.assertFalse(self.window.dock.features() & QDockWidget.DockWidgetClosable)
        self.assertFalse(
            self.window.file_dock.features() & QDockWidget.DockWidgetClosable
        )
        self.assertTrue(
            self.window.image_quality_dock.features() & QDockWidget.DockWidgetClosable
        )

    def test_position_menu_moves_without_dragging_and_restores_saved_layout(self):
        before = self.window.saveState()
        dock = self.window.file_dock
        for caption, area in (
            ("Move to Left", Qt.LeftDockWidgetArea),
            ("Move to Bottom", Qt.BottomDockWidgetArea),
            ("Move to Top", Qt.TopDockWidgetArea),
            ("Move to Right", Qt.RightDockWidgetArea),
        ):
            menu = dock.panel_header.position_menu()
            next(
                action for action in menu.actions() if action.text() == caption
            ).trigger()
            self.app.processEvents()
            self.assertEqual(self.window.dockWidgetArea(dock), area)
            self.assertFalse(dock.isFloating())
            menu.deleteLater()
        dock.panel_header.toggle_floating()
        self.assertTrue(dock.isFloating())
        self.assertTrue(self.window.restoreState(before))
        self.app.processEvents()
        self.assertFalse(dock.isFloating())
        self.assertEqual(self.window.dockWidgetArea(dock), Qt.RightDockWidgetArea)

    def test_dock_resize_and_tabification_preserve_content(self):
        dock = self.window.file_dock
        self.window.label_filter.setText("keep query")
        before = dock.width()
        self.window.resizeDocks([dock], [before + 60], Qt.Horizontal)
        self.app.processEvents()
        self.assertGreater(dock.width(), before + 30)
        self.window.tabifyDockWidget(self.window.dock, dock)
        dock.raise_()
        self.app.processEvents()
        self.assertIn(dock, self.window.tabifiedDockWidgets(self.window.dock))
        self.assertEqual(self.window.label_filter.text(), "keep query")
        self.assertEqual(dock.panel_header.height(), 38)

    def test_title_double_click_uses_native_docking(self):
        dock = self.window.file_dock
        header = dock.panel_header
        point = QPoint(header.width() - 4, header.height() // 2)
        QTest.mouseDClick(header, Qt.LeftButton, pos=point)
        self.app.processEvents()
        self.assertTrue(dock.isFloating())
        QTest.mouseDClick(header, Qt.LeftButton, pos=point)
        self.app.processEvents()
        self.assertFalse(dock.isFloating())

    def test_language_and_theme_keep_geometry_content_and_header_actions(self):
        field = self.window.label_filter
        field.setText("keep 裂纹")
        self.window.image_quality_dock.show()
        before = self.window.file_list_controls.sort_button.defaultAction()
        for mode, language in (("dark", SIMPLIFIED_CHINESE), ("light", ENGLISH)):
            self.window.change_language(language)
            self.window.appearance.apply_preferences(mode, "teal")
            self.app.processEvents()
            self.assertEqual(field.text(), "keep 裂纹")
            self.assertIs(
                self.window.file_list_controls.sort_button.defaultAction(), before
            )
            for dock in self.docks:
                header = dock.panel_header
                self.assertEqual(header.accessibleName(), dock.windowTitle())
                self.assertEqual(header.title.text(), dock.windowTitle())
                self.assertEqual(header.height(), 38)
                image = header.grab().toImage()
                self.assertEqual(
                    image.pixelColor(3, header.height() - 4),
                    QColor(COLORS["panel_header"]),
                )
        menu = self.window.file_header.position_menu()
        self.assertIn("Move to Left", [a.text() for a in menu.actions()])
        menu.deleteLater()

    def test_quality_header_actions_retain_signals_and_disabled_state(self):
        from types import SimpleNamespace
        panel = self.window.image_quality_panel
        header = self.window.image_quality_dock.panel_header
        calls = []
        panel.refreshRequested.connect(lambda: calls.append("refresh"))
        panel.clearRequested.connect(lambda: calls.append("clear"))
        self.window.image_quality_dock.show()
        self.app.processEvents()
        for button in (panel.refresh_button, panel.clear_button):
            self.assertIs(button.parentWidget(), header)
            self.assertFalse(button.isEnabled())
        panel.set_results([SimpleNamespace(path='sample.png', findings=())])
        # Disconnect application operations; exercise the same visible controls.
        panel.refreshRequested.disconnect(self.window.refresh_image_quality)
        panel.clearRequested.disconnect(self.window.clear_image_quality_results)
        panel.refresh_button.click()
        panel.clear_button.click()
        self.assertEqual(calls, ["refresh", "clear"])
        panel.setEnabled(False)
        self.assertFalse(panel.refresh_button.isEnabled())
        self.assertFalse(panel.clear_button.isEnabled())
        self.assertTrue(header.close_button.isEnabled())
        panel.setEnabled(True)
        self.assertTrue(panel.refresh_button.isEnabled())

    def test_three_panels_and_selection_actions_fit_a_scaled_desktop(self):
        folder = Path(self.temporary.name) / "images"
        folder.mkdir()
        image = QImage(72, 58, QImage.Format_RGB32)
        image.fill(QColor("gray"))
        for number in range(2):
            image.save(str(folder / f"image{number}.png"))
        self.window.import_dir_images(str(folder))
        self.window.auto_saving.setChecked(False)
        self.window.annotation_clipboard = [
            ("crack", ((5, 5), (25, 5), (25, 25), (5, 25)), False)
        ]
        self.window.paste_copied_bounding_boxes()
        self.window.file_list_widget.item(0).setSelected(True)
        self.window.resize(1280, 720)
        self.window.image_quality_dock.show()
        self.app.processEvents()
        self.assertLessEqual(self.window.height(), 720)
        self.window.file_list_stack.setCurrentWidget(self.window.file_list_empty_state)
        self.app.processEvents()
        clear = self.window.file_list_clear_filter_button
        page = self.window.file_list_empty_state
        self.assertGreaterEqual(clear.mapTo(page, QPoint()).y(), 0)
        self.assertLessEqual(
            clear.mapTo(page, QPoint()).y() + clear.height(), page.height()
        )
        for bar, dock in (
            (self.window.annotation_selection_bar, self.window.dock),
            (self.window.file_selection_bar, self.window.file_dock),
        ):
            self.assertTrue(bar.isVisible())
            self.assertLessEqual(
                bar.mapTo(dock, QPoint()).y() + bar.height(), dock.height()
            )

    def test_application_exit_after_repeated_mode_changes(self):
        # Exercise the real Qt loop and native destruction in fresh interpreters,
        # including saved mode changes. Collect while Python/Qt are still fully
        # initialized: module-global wrappers left to interpreter finalization
        # intermittently crash even on the unchanged baseline.
        environment = os.environ.copy()
        for _repeat in range(2):
            for mode in ("light", "dark", "system"):
                code = (
                    "import gc, weakref\n"
                    "from PyQt5.QtCore import QTimer\n"
                    "from PyQt5 import sip\n"
                    "from labelimg.workbench.bootstrap import get_main_app\n"
                    "def exercise():\n"
                    "    app,window=get_main_app()\n"
                    f"    window.appearance.apply_preferences({mode!r},'blue')\n"
                    "    QTimer.singleShot(0, window.close)\n"
                    "    app.exec_()\n"
                    "    assert sip.isdeleted(window), 'Primary window outlived its close'\n"
                    "    return weakref.ref(app)\n"
                    "reference=exercise()\n"
                    "gc.collect()\n"
                    "assert reference() is None, 'Closed QApplication retained'\n"
                )
                result = subprocess.run(
                    [sys.executable, "-X", "faulthandler", "-B", "-c", code],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(
                    result.returncode, 0, (mode, result.stdout, result.stderr)
                )

    def test_panel_color_roles_remain_readable_for_every_preset(self):
        for mode in ("light", "dark"):
            for accent in available_accents():
                c = appearance_theme(mode, accent.identifier).colors
                for foreground in ("text", "muted"):
                    self.assertGreaterEqual(
                        contrast_ratio(c[foreground], c["panel_header"]), 4.5
                    )
                self.assertNotEqual(c["workspace_gutter"], c["surface"])
                self.assertNotEqual(c["panel_border"], c["panel_header"])


if __name__ == "__main__":
    unittest.main()
