import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QItemSelectionModel, QRect, QTimer, Qt
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QMenu,
    QStyle,
    QStyleOptionViewItem,
)

from labelimg.app import MainWindow
from labelimg.file_recovery import TrashIdentity
from labelimg.file_list import (
    BatchRenameDialog,
    CURRENT_IMAGE_ROLE,
    FILE_ANNOTATION_STATE_ROLE,
    FILE_PERSISTENCE_FLAGS_ROLE,
    FILE_REVIEW_STATE_ROLE,
    FileListItemDelegate,
    PRESERVED_SELECTION_APPEARANCE_ROLE,
)


class FakeTrashAdapter:
    def __init__(self, directory):
        self.directory = directory
        self.paths = {}

    def move(self, path):
        token = str(len(self.paths) + 1)
        destination = os.path.join(self.directory, token)
        shutil.move(path, destination)
        self.paths[token] = destination
        return TrashIdentity("path", destination, path)

    def exists(self, identity):
        return os.path.exists(identity.token)

    def restore(self, identity, destination):
        shutil.move(identity.token, destination)


class FileListSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.image_dir = os.path.join(self.temporary.name, "images")
        os.makedirs(self.image_dir)
        self.paths = []
        for name in ("01.png", "02.png", "03.png", "04.png"):
            path = os.path.abspath(os.path.join(self.image_dir, name))
            image = QImage(40, 40, QImage.Format_RGB32)
            image.fill(QColor("white"))
            self.assertTrue(image.save(path))
            self.paths.append(path)
        classes = os.path.join(self.temporary.name, "classes.txt")
        with open(classes, "w", encoding="utf8"):
            pass
        self.window = MainWindow(
            default_prefdef_class_file=classes,
        )
        trash_dir = os.path.join(self.temporary.name, "trash")
        os.makedirs(trash_dir)
        self.window.system_trash = FakeTrashAdapter(trash_dir)
        self.window.import_dir_images(self.image_dir)
        self.window.show()
        self.window.file_list_widget.setFocus()
        self.app.processEvents()

    def tearDown(self):
        self.window.deleteLater()
        self.app.processEvents()
        self.temporary.cleanup()

    def click_row(self, row, modifiers=Qt.NoModifier):
        rectangle = self.window.file_list_widget.visualItemRect(
            self.window.file_list_widget.item(row)
        )
        QTest.mouseClick(
            self.window.file_list_widget.viewport(),
            Qt.LeftButton,
            modifiers,
            rectangle.center(),
        )
        self.app.processEvents()

    def selected_paths(self):
        return self.window.selected_file_paths()

    def render_file_item(self, state):
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 220, 30)
        option.state = QStyle.State_Enabled | state
        option.widget = self.window.file_list_widget
        image = QImage(220, 30, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        self.window.file_list_widget.itemDelegate().paint(
            painter,
            option,
            self.window.file_list_widget.model().index(1, 0),
        )
        painter.end()
        return image

    def test_initial_current_image_is_not_selected(self):
        self.assertEqual(self.selected_paths(), [])
        self.assertTrue(
            self.window.file_list_widget.item(0).data(
                CURRENT_IMAGE_ROLE
            )
        )
        self.assertEqual(
            self.window.file_selection_count_label.text(),
            "共 4 个文件",
        )

    def test_click_ctrl_click_and_shift_click_follow_explorer_rules(self):
        self.click_row(0)
        self.click_row(2, Qt.ControlModifier)
        self.assertEqual(
            self.selected_paths(),
            [self.paths[0], self.paths[2]],
        )

        self.click_row(3, Qt.ShiftModifier)
        self.assertEqual(
            self.selected_paths(),
            [self.paths[2], self.paths[3]],
        )
        self.assertEqual(
            self.window.file_selection_count_label.text(),
            "已选 2 / 共 4",
        )

    def test_ctrl_a_and_ctrl_space_are_file_selection_shortcuts(self):
        QTest.keyClick(
            self.window.file_list_widget,
            Qt.Key_A,
            Qt.ControlModifier,
        )
        self.assertEqual(self.selected_paths(), self.paths)

        self.window.file_list_widget.selectionModel().setCurrentIndex(
            self.window.file_list_widget.model().index(1, 0),
            QItemSelectionModel.NoUpdate,
        )
        QTest.keyClick(
            self.window.file_list_widget,
            Qt.Key_Space,
            Qt.ControlModifier,
        )
        self.assertEqual(
            self.selected_paths(),
            [self.paths[0], self.paths[2], self.paths[3]],
        )
        self.assertFalse(self.window.canvas.questioned)

    def test_space_does_not_change_review_state_when_list_has_focus(self):
        self.click_row(0)
        QTest.keyClick(
            self.window.file_list_widget,
            Qt.Key_Space,
        )
        self.app.processEvents()

        self.assertFalse(self.window.canvas.verified)
        self.assertFalse(self.window.canvas.questioned)

    def test_double_click_opens_without_changing_selection(self):
        self.click_row(0)
        self.click_row(1, Qt.ControlModifier)
        preserved = self.selected_paths()
        self.window.file_list_widget.itemOpenRequested.connect(
            lambda _item: QTimer.singleShot(
                0,
                self.window.file_list_widget.clearSelection,
            )
        )
        rectangle = self.window.file_list_widget.visualItemRect(
            self.window.file_list_widget.item(3)
        )

        QTest.mousePress(
            self.window.file_list_widget.viewport(),
            Qt.LeftButton,
            Qt.NoModifier,
            rectangle.center(),
        )
        self.app.processEvents()
        self.assertEqual(
            self.selected_paths(),
            [self.paths[3]],
            "the first press must update the real selection immediately",
        )
        self.assertTrue(
            self.window.file_list_widget.item(0).data(
                PRESERVED_SELECTION_APPEARANCE_ROLE
            )
        )
        self.assertTrue(
            self.window.file_list_widget.item(1).data(
                PRESERVED_SELECTION_APPEARANCE_ROLE
            )
        )
        QTest.mouseRelease(
            self.window.file_list_widget.viewport(),
            Qt.LeftButton,
            Qt.NoModifier,
            rectangle.center(),
        )
        self.app.processEvents()
        self.assertEqual(
            self.selected_paths(),
            [self.paths[3]],
            "the first release must not delay the real selection",
        )
        QTest.mouseDClick(
            self.window.file_list_widget.viewport(),
            Qt.LeftButton,
            Qt.NoModifier,
            rectangle.center(),
        )
        QTest.mouseRelease(
            self.window.file_list_widget.viewport(),
            Qt.LeftButton,
            Qt.NoModifier,
            rectangle.center(),
        )
        self.app.processEvents()

        self.assertEqual(self.window.file_path, self.paths[3])
        self.assertEqual(self.selected_paths(), preserved)
        self.assertFalse(
            any(
                self.window.file_list_widget.item(row).data(
                    PRESERVED_SELECTION_APPEARANCE_ROLE
                )
                for row in range(
                    self.window.file_list_widget.count()
                )
            )
        )
        self.assertTrue(
            self.window.file_list_widget.item(3).data(
                CURRENT_IMAGE_ROLE
            )
        )
        self.assertFalse(self.window.file_list_widget.hasFocus())

    def test_plain_click_replaces_selection_immediately(self):
        self.click_row(0)
        self.click_row(1, Qt.ControlModifier)
        rectangle = self.window.file_list_widget.visualItemRect(
            self.window.file_list_widget.item(3)
        )

        QTest.mousePress(
            self.window.file_list_widget.viewport(),
            Qt.LeftButton,
            Qt.NoModifier,
            rectangle.center(),
        )
        self.app.processEvents()
        self.assertEqual(self.selected_paths(), [self.paths[3]])
        self.assertTrue(
            self.window.file_list_widget.item(0).data(
                PRESERVED_SELECTION_APPEARANCE_ROLE
            )
        )
        QTest.mouseRelease(
            self.window.file_list_widget.viewport(),
            Qt.LeftButton,
            Qt.NoModifier,
            rectangle.center(),
        )
        self.app.processEvents()
        self.assertEqual(self.selected_paths(), [self.paths[3]])
        QTest.qWait(QApplication.doubleClickInterval() + 20)
        self.app.processEvents()
        self.assertFalse(
            any(
                self.window.file_list_widget.item(row).data(
                    PRESERVED_SELECTION_APPEARANCE_ROLE
                )
                for row in range(
                    self.window.file_list_widget.count()
                )
            )
        )

    def test_hover_is_gray_and_selected_row_has_no_leading_block(self):
        normal = self.render_file_item(QStyle.State_None)
        hovered = self.render_file_item(QStyle.State_MouseOver)
        selected = self.render_file_item(QStyle.State_Selected)
        selected_hovered = self.render_file_item(
            QStyle.State_Selected | QStyle.State_MouseOver
        )
        self.window.file_list_widget.item(1).setData(
            PRESERVED_SELECTION_APPEARANCE_ROLE,
            True,
        )
        preserved_appearance = self.render_file_item(
            QStyle.State_None
        )
        self.window.file_list_widget.item(1).setData(
            PRESERVED_SELECTION_APPEARANCE_ROLE,
            False,
        )

        normal_background = normal.pixelColor(210, 2)
        hover_background = hovered.pixelColor(210, 2)
        self.assertNotEqual(hover_background, normal_background)
        self.assertEqual(
            (
                hover_background.red(),
                hover_background.green(),
                hover_background.blue(),
            ),
            (
                hover_background.red(),
                hover_background.red(),
                hover_background.red(),
            ),
        )
        self.assertEqual(
            selected.pixelColor(1, 2),
            selected.pixelColor(210, 2),
        )
        self.assertEqual(
            selected_hovered.pixelColor(210, 2),
            selected.pixelColor(210, 2),
        )
        self.assertEqual(
            preserved_appearance.pixelColor(210, 2),
            selected.pixelColor(210, 2),
        )

    def test_file_list_uses_fixed_status_name_and_alert_columns(self):
        layout = FileListItemDelegate.row_layout(QRect(0, 0, 220, 30))

        self.assertEqual(layout["annotation"].width(), 20)
        self.assertEqual(layout["review"].width(), 20)
        self.assertEqual(layout["alert"].width(), 20)
        self.assertLess(layout["annotation"].right(), layout["review"].left())
        self.assertLess(layout["review"].right(), layout["name"].left())
        self.assertLess(layout["name"].right(), layout["alert"].left())

    def test_delegate_paints_independent_annotation_and_review_icons(self):
        item = self.window.file_list_widget.item(1)
        item.setData(FILE_ANNOTATION_STATE_ROLE, "annotated")
        item.setData(FILE_REVIEW_STATE_ROLE, "questioned")
        item.setData(FILE_PERSISTENCE_FLAGS_ROLE, ())
        image = self.render_file_item(QStyle.State_None)
        layout = FileListItemDelegate.row_layout(QRect(0, 0, 220, 30))
        base = image.pixelColor(210, 2)

        for key in ("annotation", "review"):
            rect = layout[key]
            self.assertTrue(any(
                image.pixelColor(x, y) != base
                for y in range(rect.top(), rect.bottom() + 1)
                for x in range(rect.left(), rect.right() + 1)
            ))

    def test_status_region_tooltips_are_independent(self):
        item = self.window.file_list_widget.item(1)
        item.setData(FILE_ANNOTATION_STATE_ROLE, "annotated")
        item.setData(FILE_REVIEW_STATE_ROLE, "verified")
        item.setData(
            FILE_PERSISTENCE_FLAGS_ROLE,
            ("dirty", "conflict", "ambiguous", "degraded"),
        )
        row = self.window.file_list_widget.visualItemRect(item)
        layout = FileListItemDelegate.row_layout(row)

        self.assertEqual(
            self.window.file_list_widget.tooltip_at(
                layout["annotation"].center()
            ),
            "已标注",
        )
        self.assertEqual(
            self.window.file_list_widget.tooltip_at(
                layout["review"].center()
            ),
            "已验证",
        )
        self.assertEqual(
            self.window.file_list_widget.tooltip_at(
                layout["name"].center()
            ),
            item.data(Qt.UserRole),
        )
        alert = self.window.file_list_widget.tooltip_at(
            layout["alert"].center()
        )
        self.assertIn("未保存修改", alert)
        self.assertIn("外部标注冲突", alert)
        self.assertIn("选择活动标注文档", alert)
        self.assertIn("只读降级状态", alert)

        self.assertEqual(
            FileListItemDelegate.highest_alert(
                ("dirty", "ambiguous", "conflict", "degraded")
            ),
            "degraded",
        )

    def test_open_next_preserves_selection(self):
        self.click_row(2)
        self.window.open_next_image()

        self.assertEqual(self.window.file_path, self.paths[1])
        self.assertEqual(self.selected_paths(), [self.paths[2]])

    def test_right_click_selected_preserves_set_and_other_replaces_it(self):
        self.click_row(0)
        self.click_row(1, Qt.ControlModifier)
        second_rect = self.window.file_list_widget.visualItemRect(
            self.window.file_list_widget.item(1)
        )
        QTest.mouseClick(
            self.window.file_list_widget.viewport(),
            Qt.RightButton,
            Qt.NoModifier,
            second_rect.center(),
        )
        self.assertEqual(
            self.selected_paths(),
            [self.paths[0], self.paths[1]],
        )

        fourth_rect = self.window.file_list_widget.visualItemRect(
            self.window.file_list_widget.item(3)
        )
        QTest.mouseClick(
            self.window.file_list_widget.viewport(),
            Qt.RightButton,
            Qt.NoModifier,
            fourth_rect.center(),
        )
        self.assertEqual(self.selected_paths(), [self.paths[3]])

    def test_successful_rename_preserves_current_image_and_selection(self):
        self.click_row(0)
        self.click_row(1, Qt.ControlModifier)
        first_target = os.path.join(self.image_dir, "10.png")
        second_target = os.path.join(self.image_dir, "20.png")

        self.window.execute_file_rename(
            {
                self.paths[0]: first_target,
                self.paths[1]: second_target,
            }
        )

        self.assertEqual(self.window.file_path, first_target)
        self.assertEqual(
            self.window.selected_file_paths(),
            [first_target, second_target],
        )
        current_items = [
            self.window.file_list_widget.item(index)
            for index in range(
                self.window.file_list_widget.count()
            )
            if self.window.file_list_widget.item(index).data(
                CURRENT_IMAGE_ROLE
            )
        ]
        self.assertEqual(len(current_items), 1)
        self.assertEqual(
            current_items[0].data(Qt.UserRole),
            first_target,
        )

    def test_renaming_other_file_keeps_dirty_current_image_loaded(self):
        self.window.dirty = True
        target = os.path.join(self.image_dir, "20.png")

        self.window.execute_file_rename({self.paths[1]: target})

        self.assertEqual(self.window.file_path, self.paths[0])
        self.assertTrue(self.window.dirty)
        self.assertEqual(self.window.cur_img_idx, 0)

    def test_deleting_other_files_keeps_dirty_current_image_loaded(self):
        self.window.dirty = True

        self.window.delete_file_paths([self.paths[3]])

        self.assertEqual(self.window.file_path, self.paths[0])
        self.assertTrue(self.window.dirty)
        self.assertEqual(self.window.cur_img_idx, 0)
        self.assertNotIn(self.paths[3], self.window.m_img_list)

    def test_batch_rename_dialog_expands_prefix_template_and_suffix(self):
        dialog = BatchRenameDialog(
            self.paths[:2],
            self.image_dir,
            parent=self.window,
        )
        dialog.prefix_edit.setText("train_")
        dialog.template_edit.setText("{序号}")
        dialog.suffix_edit.setText("_checked")
        dialog.start_spin.setValue(3)
        dialog.width_spin.setValue(3)
        self.app.processEvents()

        self.assertEqual(
            list(dialog.mapping.values()),
            [
                os.path.join(
                    self.image_dir,
                    "train_003_checked.png",
                ),
                os.path.join(
                    self.image_dir,
                    "train_004_checked.png",
                ),
            ],
        )
        self.assertTrue(
            dialog.buttons.button(
                QDialogButtonBox.Ok
            ).isEnabled()
        )

    def test_file_context_menu_contains_selection_aware_commands(self):
        self.click_row(0)
        self.click_row(1, Qt.ControlModifier)
        point = self.window.file_list_widget.visualItemRect(
            self.window.file_list_widget.item(1)
        ).center()
        captured = []

        def capture(menu, *_arguments):
            captured.extend(
                action.text()
                for action in menu.actions()
                if not action.isSeparator()
            )

        with patch.object(QMenu, "exec_", new=capture):
            self.window.pop_file_list_menu(point)

        self.assertEqual(
            captured,
            [
                "打开",
                "批量重命名…",
                "在文件资源管理器中显示",
                "设置复核状态",
                "选择",
                "复制",
                "清除选中的 2 个文件的全部标注…",
                "删除选中的 2 个文件…",
            ],
        )

    def test_file_context_menu_splits_annotation_and_review_selection(self):
        self.click_row(0)
        point = self.window.file_list_widget.visualItemRect(
            self.window.file_list_widget.item(0)
        ).center()
        captured = []

        with patch.object(
            QMenu,
            "exec_",
            new=lambda menu, *_arguments: captured.append(menu),
        ):
            self.window.pop_file_list_menu(point)

        root = captured[0]
        select_menu = next(
            action.menu()
            for action in root.actions()
            if action.text() == "选择"
        )
        annotation_menu = next(
            action.menu()
            for action in select_menu.actions()
            if action.text() == "按标注状态选择"
        )
        review_menu = next(
            action.menu()
            for action in select_menu.actions()
            if action.text() == "按复核状态选择"
        )

        self.assertEqual(
            [action.text() for action in annotation_menu.actions()],
            ["未标注", "已标注"],
        )
        self.assertEqual(
            [action.text() for action in review_menu.actions()],
            ["未复核", "待复核", "已验证"],
        )


if __name__ == "__main__":
    unittest.main()
