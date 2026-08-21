import os
import hashlib
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, QSize, Qt
from PyQt5.QtGui import QColor, QImage, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from labelimg.annotations.domain.model import AnnotationFormat
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench
from labelimg.canvas.widget import Canvas
from labelimg.canvas.shape import Shape
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language


class CommandSurfacesTest(unittest.TestCase):
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

    def load_image(self, name="image.png"):
        image_path = os.path.join(self.temporary.name, name)
        image = QImage(20, 20, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(image_path))
        self.assertTrue(self.window.load_file(image_path))
        return image_path

    def load_canvas_shapes(self, count):
        shapes = []
        for index in range(count):
            shape = Shape(label="label-%d" % index)
            left = 1 + index * 6
            for point in (
                QPointF(left, 1),
                QPointF(left + 4, 1),
                QPointF(left + 4, 5),
                QPointF(left, 5),
            ):
                shape.add_point(point)
            shape.close()
            shapes.append(shape)
        self.window.canvas.load_shapes(shapes)
        return shapes

    @staticmethod
    def menu_labels(menu):
        return [
            None if action.isSeparator() else action.text()
            for action in menu.actions()
        ]

    def test_left_rail_is_fixed_and_contains_only_canvas_tools(self):
        rail = self.window.tools

        self.assertEqual(rail.width(), 52)
        self.assertFalse(rail.isMovable())
        self.assertFalse(rail.isFloatable())
        self.assertFalse(rail.toggleViewAction().isVisible())
        self.assertEqual(
            [
                button.defaultAction()
                for button in rail.buttons.values()
            ],
            [
                self.window.actions.selectTool,
                self.window.actions.create,
                self.window.actions.panTool,
                self.window.actions.cropImage,
            ],
        )
        self.assertTrue(self.window.actions.selectTool.isChecked())
        self.assertTrue(all(
            button.size() == QSize(44, 44)
            for button in rail.buttons.values()
        ))
        self.assertTrue(all(
            button.iconSize() == QSize(24, 24)
            for button in rail.buttons.values()
        ))
        forbidden = {
            self.window.actions.openDir,
            self.window.actions.openPrev,
            self.window.actions.openNext,
            self.window.actions.save,
            self.window.actions.copy,
            self.window.actions.delete,
        }
        self.assertTrue(forbidden.isdisjoint(
            button.defaultAction() for button in rail.buttons.values()
        ))

    def test_selection_and_pan_are_explicit_stable_modes(self):
        self.window.actions.panTool.setEnabled(True)
        self.window.actions.panTool.trigger()
        self.assertEqual(self.window.canvas.mode, Canvas.PAN)
        self.assertTrue(self.window.actions.panTool.isChecked())

        self.window.actions.selectTool.setEnabled(True)
        self.window.actions.selectTool.trigger()
        self.assertEqual(self.window.canvas.mode, Canvas.EDIT)
        self.assertTrue(self.window.actions.selectTool.isChecked())

    def test_pan_mode_and_middle_drag_emit_pan_without_annotation_gesture(self):
        pans = []
        gestures = []
        self.window.canvas.panRequest.connect(
            lambda x, y: pans.append((x, y))
        )
        self.window.canvas.annotationGestureStarted.connect(
            gestures.append
        )

        self.window.canvas.set_mode(Canvas.PAN)
        self.window.canvas.mousePressEvent(QMouseEvent(
            QEvent.MouseButtonPress, QPointF(10, 10),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        ))
        self.window.canvas.mouseMoveEvent(QMouseEvent(
            QEvent.MouseMove, QPointF(20, 18),
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
        ))
        self.window.canvas.mouseReleaseEvent(QMouseEvent(
            QEvent.MouseButtonRelease, QPointF(20, 18),
            Qt.LeftButton, Qt.NoButton, Qt.NoModifier,
        ))

        self.window.canvas.set_mode(Canvas.EDIT)
        self.window.canvas.mousePressEvent(QMouseEvent(
            QEvent.MouseButtonPress, QPointF(10, 10),
            Qt.MiddleButton, Qt.MiddleButton, Qt.NoModifier,
        ))
        self.window.canvas.mouseMoveEvent(QMouseEvent(
            QEvent.MouseMove, QPointF(16, 14),
            Qt.NoButton, Qt.MiddleButton, Qt.NoModifier,
        ))
        self.window.canvas.mouseReleaseEvent(QMouseEvent(
            QEvent.MouseButtonRelease, QPointF(16, 14),
            Qt.MiddleButton, Qt.NoButton, Qt.NoModifier,
        ))

        self.assertEqual(len(pans), 2)
        self.assertEqual(gestures, [])

    def test_top_bar_collapses_by_measured_available_width(self):
        bar = self.window.top_commands
        bar.update_responsive_layout(800)
        self.assertTrue(bar.image_quick_widget_action.isVisible())
        self.assertFalse(bar.rotate_widget_action.isVisible())
        self.assertFalse(bar.flip_widget_action.isVisible())
        self.assertEqual(bar.open_button.width(), 44)
        self.assertEqual(self.window.format_selector.width(), 44)
        self.assertTrue(all(
            button.width() == 44
            for button in self.window.review_control.buttons.values()
        ))

        bar.update_responsive_layout(4000)
        self.assertFalse(bar.image_quick_widget_action.isVisible())
        self.assertTrue(bar.rotate_widget_action.isVisible())
        self.assertTrue(bar.flip_widget_action.isVisible())
        for button in (
            bar.open_button,
            self.window.format_selector,
            *self.window.review_control.buttons.values(),
        ):
            self.assertEqual(
                button.toolButtonStyle(),
                Qt.ToolButtonTextBesideIcon,
            )
            self.assertGreaterEqual(button.width(), button.sizeHint().width())

        self.window.resize(1024, 720)
        self.window.show()
        self.app.processEvents()
        bar.update_responsive_layout(bar.width())
        self.assertLessEqual(bar.sizeHint().width(), bar.width())
        self.assertTrue(bar.open_button.isVisible())
        self.assertTrue(all(
            button.isVisible()
            for button in self.window.review_control.buttons.values()
        ))
        self.assertTrue(self.window.format_selector.isVisible())
        self.assertTrue(bar.save_button.isVisible())

    def test_expanded_top_bar_widths_follow_the_current_language(self):
        bar = self.window.top_commands
        text_controls = [
            bar.open_button,
            *self.window.review_control.buttons.values(),
            self.window.format_selector,
        ]

        def expanded_widths(language):
            self.window.change_language(language)
            bar.update_responsive_layout(4000)
            widths = {}
            for control in text_controls:
                self.assertEqual(
                    control.toolButtonStyle(),
                    Qt.ToolButtonTextBesideIcon,
                    control.objectName(),
                )
                self.assertGreaterEqual(
                    control.width(),
                    control.sizeHint().width(),
                    "%s clips %r: actual=%d, required=%d" % (
                        control.objectName(),
                        control.text(),
                        control.width(),
                        control.sizeHint().width(),
                    ),
                )
                self.assertGreaterEqual(
                    control.height(),
                    control.sizeHint().height(),
                    "%s clips vertically: actual=%d, required=%d" % (
                        control.objectName(),
                        control.height(),
                        control.sizeHint().height(),
                    ),
                )
                widths[control.objectName()] = control.width()
            return widths

        english_widths = expanded_widths(ENGLISH)
        chinese_widths = expanded_widths(SIMPLIFIED_CHINESE)
        english_widths_again = expanded_widths(ENGLISH)

        self.assertEqual(english_widths_again, english_widths)
        self.assertLess(
            chinese_widths["openWorkspaceButton"],
            english_widths["openWorkspaceButton"],
        )
        for state in self.window.review_control.buttons:
            object_name = "review_%s" % state
            self.assertLess(
                chinese_widths[object_name],
                english_widths[object_name],
            )

    def test_canvas_context_menus_are_target_scoped_and_bilingual(self):
        self.load_image()
        controller = self.window.canvas_context_menu

        self.assertEqual(
            self.menu_labels(controller.build("blank")),
            ["Draw Box"],
        )
        self.window.annotation_clipboard = [object(), object()]
        self.assertEqual(
            self.menu_labels(controller.build("blank")),
            ["Draw Box", "Paste 2 Annotations"],
        )

        shapes = self.load_canvas_shapes(2)
        self.window.canvas.set_selected_shapes(
            [shapes[0]],
            active_shape=shapes[0],
        )
        single = controller.build("single")
        self.assertEqual(
            self.menu_labels(single),
            [
                "Edit Label…",
                "Copy Annotation",
                "Duplicate Annotation",
                "Hide Annotation",
                None,
                "Delete Annotation",
            ],
        )
        self.assertEqual(single.defaultAction().text(), "Edit Label…")
        self.assertTrue(all(
            action.shortcut().isEmpty()
            for action in single.actions()
            if not action.isSeparator()
        ))

        self.window.canvas.set_selected_shapes(
            shapes,
            active_shape=shapes[1],
        )
        self.window.canvas.set_shape_visible(shapes[0], False)
        multiple = controller.build("multiple")
        self.assertEqual(
            self.menu_labels(multiple),
            [
                "Copy 2 Annotations",
                "Duplicate 2 Annotations",
                "Show 2 Annotations",
                None,
                "Delete 2 Annotations",
            ],
        )
        multiple.actions()[2].trigger()
        self.assertTrue(all(
            self.window.canvas.isVisible(shape) for shape in shapes
        ))
        self.window.canvas.set_shape_visible(shapes[0], False)

        self.window.change_language(SIMPLIFIED_CHINESE)
        self.assertFalse(self.window.canvas.isVisible(shapes[0]))
        self.assertEqual(
            self.menu_labels(controller.build("multiple")),
            [
                "复制 2 个标注",
                "创建 2 个标注副本",
                "显示 2 个标注",
                None,
                "删除 2 个标注",
            ],
        )

    def test_top_bar_controls_share_one_height(self):
        bar = self.window.top_commands
        bar.update_responsive_layout(1100)

        controls = [
            bar.open_button,
            bar.previous_button,
            bar.counter_label,
            bar.next_button,
            *self.window.review_control.buttons.values(),
            bar.rotate_button,
            bar.flip_button,
            self.window.format_selector,
            bar.auto_save_button,
            bar.save_button,
        ]
        self.assertEqual({control.height() for control in controls}, {44})

    def test_dock_panel_rows_share_horizontal_edges(self):
        self.window.resize(1180, 760)
        self.window.show()
        self.app.processEvents()

        annotation_rows = [
            self.window.annotation_header,
            self.window.diffc_button,
            self.window.default_label_row,
            self.window.label_filter,
            self.window.label_summary_label,
            self.window.label_list,
        ]
        file_rows = [
            self.window.annotation_directory_bar,
            self.window.file_list_controls,
            self.window.file_list_stack,
            self.window.file_selection_count_label,
        ]
        for rows in (annotation_rows, file_rows):
            self.assertEqual({row.x() for row in rows}, {6})
            self.assertEqual({row.width() for row in rows}, {rows[0].width()})

    def test_one_shot_create_accept_returns_to_enabled_selection(self):
        self.load_image("accept.png")
        self.window.use_default_label_checkbox.setChecked(True)
        self.window.default_label_text_line.setText("cat")

        self.window.create_shape()
        self.window.canvas.handle_drawing(QPointF(2, 2))
        self.window.canvas.line[1] = QPointF(12, 12)
        self.window.canvas.handle_drawing(QPointF(12, 12))

        self.assertEqual(self.window.canvas.mode, Canvas.EDIT)
        self.assertTrue(self.window.actions.selectTool.isChecked())
        for action in (
            self.window.actions.selectTool,
            self.window.actions.create,
            self.window.actions.panTool,
            self.window.actions.cropImage,
        ):
            self.assertTrue(action.isEnabled())
        self.assertEqual(len(self.window.canvas.shapes), 1)
        self.assertEqual(self.window.canvas.shapes[0].label, "cat")

    def test_one_shot_create_cancel_returns_to_selection_without_shape(self):
        self.load_image("cancel.png")
        self.window.use_default_label_checkbox.setChecked(False)

        with patch.object(
            self.window.candidate_label_dialog,
            "choose",
            return_value=None,
        ):
            self.window.create_shape()
            self.window.canvas.handle_drawing(QPointF(2, 2))
            self.window.canvas.line[1] = QPointF(12, 12)
            self.window.canvas.handle_drawing(QPointF(12, 12))

        self.assertEqual(self.window.canvas.mode, Canvas.EDIT)
        self.assertTrue(self.window.actions.selectTool.isChecked())
        self.assertTrue(self.window.actions.create.isEnabled())
        self.assertEqual(self.window.canvas.shapes, [])

    def test_annotation_panel_owns_copy_delete_and_visibility(self):
        self.assertIs(
            self.window.copy_button.defaultAction(),
            self.window.actions.copy,
        )
        self.assertIs(
            self.window.delete_button.defaultAction(),
            self.window.actions.delete,
        )
        self.assertIs(
            self.window.visibility_button.defaultAction(),
            self.window.actions.toggleVisibility,
        )
        rail_actions = {
            button.defaultAction()
            for button in self.window.tools.buttons.values()
        }
        self.assertNotIn(self.window.actions.copy, rail_actions)
        self.assertNotIn(self.window.actions.delete, rail_actions)

    def test_settings_is_a_top_level_menu_for_application_preferences(self):
        self.assertEqual(
            self.window.menuBar().actions(),
            [
                self.window.menus.file.menuAction(),
                self.window.menus.edit.menuAction(),
                self.window.menus.image.menuAction(),
                self.window.menus.view.menuAction(),
                self.window.menus.settings.menuAction(),
                self.window.menus.help.menuAction(),
            ],
        )
        actions = self.window.menus.settings.actions()
        self.assertEqual(
            actions,
            [
                self.window.menus.language.menuAction(),
                actions[1],
                self.window.auto_saving,
                self.window.single_class_mode,
                actions[4],
                self.window.actions.resetAll,
            ],
        )
        self.assertTrue(actions[1].isSeparator())
        self.assertTrue(actions[4].isSeparator())
        self.assertTrue(self.window.single_class_mode.shortcut().isEmpty())

    def test_every_static_menu_option_has_a_distinct_semantic_icon(self):
        menu_actions = []

        def collect(menu):
            for action in menu.actions():
                if action.isSeparator():
                    continue
                menu_actions.append(action)
                if action.menu() is not None:
                    collect(action.menu())

        for menu in (
            self.window.menus.file,
            self.window.menus.edit,
            self.window.menus.image,
            self.window.menus.view,
            self.window.menus.settings,
            self.window.menus.help,
        ):
            collect(menu)

        self.assertTrue(menu_actions)
        self.assertEqual(
            [action.text() for action in menu_actions if action.icon().isNull()],
            [],
        )

        def icon_signature(action):
            image = action.icon().pixmap(24, 24).toImage().convertToFormat(
                QImage.Format_ARGB32
            )
            data = image.bits().asstring(image.byteCount())
            return hashlib.sha256(data).digest()

        self.assertEqual(
            len({icon_signature(action) for action in menu_actions}),
            len(menu_actions),
        )

    def test_file_and_edit_menus_have_distinct_command_ownership(self):
        file_actions = self.window.menus.file.actions()
        self.assertEqual(
            file_actions,
            [
                self.window.actions.openDir,
                self.window.actions.open,
                self.window.menus.recentFiles.menuAction(),
                file_actions[3],
                self.window.menus.annotationDirectory.menuAction(),
                file_actions[5],
                self.window.actions.replaceAnnotation,
                self.window.actions.save,
                self.window.actions.saveAs,
                self.window.actions.save_format,
                self.window.actions.close,
                file_actions[11],
                self.window.actions.deleteImg,
                self.window.actions.recentFileOperations,
                file_actions[14],
                self.window.actions.quit,
            ],
        )
        for index in (3, 5, 11, 14):
            self.assertTrue(file_actions[index].isSeparator())

        edit_actions = self.window.menus.edit.actions()
        self.assertEqual(
            edit_actions,
            [
                self.window.actions.create,
                self.window.actions.undoAnnotation,
                self.window.actions.redoAnnotation,
                edit_actions[3],
                self.window.actions.edit,
                self.window.actions.copyAnnotations,
                self.window.actions.pasteAnnotations,
                self.window.actions.copyPrevBounding,
                self.window.actions.copy,
                self.window.actions.delete,
                edit_actions[10],
                self.window.actions.lineColor,
                self.window.draw_squares_option,
            ],
        )
        self.assertTrue(edit_actions[3].isSeparator())
        self.assertTrue(edit_actions[10].isSeparator())

    def test_file_menu_presents_annotation_format_as_a_selector(self):
        format_entry = self.window.menus.file.actions()[9]

        self.assertEqual(format_entry.text(), "Annotation format")
        self.assertIs(format_entry.menu(), self.window.format_selector.menu)
        self.assertEqual(
            [action.text() for action in format_entry.menu().actions()],
            ["Pascal VOC", "YOLO", "CreateML"],
        )
        self.assertTrue(all(
            action.isCheckable()
            for action in format_entry.menu().actions()
        ))
        self.assertTrue(
            self.window.format_selector.actions[
                AnnotationFormat.PASCAL_VOC
            ].isChecked()
        )

        self.window.change_language(SIMPLIFIED_CHINESE)
        self.assertEqual(format_entry.text(), "标注格式")
        self.assertIs(format_entry.menu(), self.window.format_selector.menu)

    def test_view_and_help_menus_use_clear_bounded_groups(self):
        view_actions = self.window.menus.view.actions()
        self.assertEqual(
            view_actions,
            [
                self.window.display_label_option,
                self.window.actions.labels,
                view_actions[2],
                self.window.actions.hideAll,
                self.window.actions.showAll,
                view_actions[5],
                self.window.actions.zoomIn,
                self.window.actions.zoomOut,
                self.window.actions.zoomOrg,
                view_actions[9],
                self.window.actions.fitWindow,
                self.window.actions.fitWidth,
            ],
        )
        for index in (2, 5, 9):
            self.assertTrue(view_actions[index].isSeparator())
        self.assertEqual(self.window.actions.labels.text(), "Annotation Panel")

        help_actions = self.window.menus.help.actions()
        self.assertEqual(
            help_actions,
            [
                self.window.actions.helpDefault,
                self.window.actions.showShortcut,
                help_actions[2],
                self.window.actions.showInfo,
            ],
        )
        self.assertTrue(help_actions[2].isSeparator())
        self.assertEqual(
            self.window.actions.showInfo.text(),
            "About LabelImg Enhanced",
        )

    def test_accessible_names_follow_live_language_changes(self):
        self.window.change_language(SIMPLIFIED_CHINESE)

        self.assertEqual(
            self.window.tools.buttons["select"].accessibleName(),
            "选择/编辑",
        )
        self.assertEqual(
            self.window.top_commands.open_button.accessibleName(),
            "打开图像目录",
        )
        self.assertEqual(
            self.window.copy_button.accessibleName(),
            "创建标注框副本",
        )
        self.assertEqual(
            self.window.zoom_widget.plus.accessibleName(),
            "放大",
        )

    def test_review_format_and_zoom_are_explicit_controls(self):
        self.assertEqual(
            set(self.window.review_control.actions),
            {"unreviewed", "questioned", "verified"},
        )
        self.window.review_control.set_state("questioned")
        self.assertTrue(
            self.window.review_control.actions["questioned"].isChecked()
        )

        self.window.format_selector.set_format(AnnotationFormat.YOLO)
        self.assertEqual(self.window.format_selector.text(), "YOLO")
        self.assertEqual(
            len(self.window.format_selector.menu.actions()), 3
        )

        self.assertIn(
            self.window.zoom_widget,
            self.window.statusBar().findChildren(type(self.window.zoom_widget)),
        )
        self.load_image("zoom.png")
        self.window.zoom_widget.setValue(135)
        self.assertEqual(self.window.zoom_widget.value(), 135)
        self.assertEqual(self.window.zoom_widget.value_button.text(), "135%")

    def test_current_review_button_does_not_rebuild_file_list(self):
        image_path = self.load_image()
        with patch.object(
            self.window,
            "populate_file_list",
            wraps=self.window.populate_file_list,
        ) as populate_file_list:
            for state in ("verified", "questioned"):
                self.window.review_control.buttons[state].click()
                self.assertEqual(
                    populate_file_list.call_count,
                    0,
                    "review state: %s" % state,
                )

        self.assertEqual(self.window.file_path, image_path)
        self.assertEqual(
            self.window.file_review_state(image_path),
            "questioned",
        )

    def test_review_shortcuts_set_state_like_review_buttons(self):
        self.load_image()
        self.window.show()
        self.window.activateWindow()
        self.window.canvas.setFocus()
        self.app.processEvents()

        QTest.keyClick(self.window.canvas, Qt.Key_Space)
        self.assertTrue(self.window.canvas.verified)
        self.assertFalse(self.window.canvas.questioned)

        QTest.keyClick(self.window.canvas, Qt.Key_Space)
        self.assertTrue(self.window.canvas.verified)
        self.assertFalse(self.window.canvas.questioned)

        QTest.keyClick(
            self.window.canvas,
            Qt.Key_Space,
            Qt.ControlModifier,
        )
        self.assertFalse(self.window.canvas.verified)
        self.assertTrue(self.window.canvas.questioned)

        QTest.keyClick(
            self.window.canvas,
            Qt.Key_Space,
            Qt.ControlModifier,
        )
        self.assertFalse(self.window.canvas.verified)
        self.assertTrue(self.window.canvas.questioned)


if __name__ == "__main__":
    unittest.main()
