import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from labelimg.ui.theme import COLORS

from PyQt5.QtCore import QEvent, QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

from labelimg.annotations import AnnotationFormat
from labelimg.files.ui.list_widget import (
    CURRENT_IMAGE_ROLE, FILE_PERSISTENCE_FLAGS_ROLE, FileListItemDelegate,
)
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class FilePanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language(ENGLISH)
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'LABELIMG_CONFIG_DIR': self.temp.name})
        self.environment.start()
        classes = os.path.join(self.temp.name, 'classes.txt')
        with open(classes, 'w', encoding='utf-8'):
            pass
        self.window = create_workbench(WorkbenchLaunchOptions(class_file=classes))
        images = os.path.join(self.temp.name, 'images')
        os.mkdir(images)
        for i in range(4):
            image = QImage(60, 60, QImage.Format_RGB32)
            image.fill(QColor('gray'))
            self.assertTrue(image.save(os.path.join(images, f'image{i}.png')))
        self.window.import_dir_images(images)
        self.window.auto_saving.setChecked(False)
        self.window.resize(1180, 760)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()
        set_language(ENGLISH)

    def select(self, *rows):
        self.window.file_list_widget.clearSelection()
        for row in rows:
            self.window.file_list_widget.item(row).setSelected(True)
        self.app.processEvents()

    def test_header_directory_and_selection_layout(self):
        w = self.window
        self.assertIs(w.file_dock.titleBarWidget(), w.file_header)
        self.assertIs(w.file_list_controls.sort_button.parentWidget(), w.file_header)
        self.assertEqual(w.file_summary_label.text(), '4')
        self.assertEqual(w.file_list_controls.sort_button.text(), 'File Name')
        self.assertFalse(w.file_selection_bar.isVisible())
        start = w.file_list_stack.mapTo(w.file_dock, QPoint())
        self.select(1)
        self.assertEqual(w.file_selection_count_label.text(), '1 selected')
        self.assertTrue(w.file_reveal_button.isVisible())
        self.assertFalse(w.file_review_button.isVisible())
        self.select(1, 2)
        self.assertEqual(w.file_selection_count_label.text(), '2 selected')
        self.assertEqual(w.file_rename_button.text(), 'Batch Rename')
        self.assertFalse(w.file_reveal_button.isVisible())
        self.assertTrue(w.file_review_button.isVisible())
        self.assertEqual(w.file_list_stack.mapTo(w.file_dock, QPoint()), start)
        self.select()
        self.assertFalse(w.file_selection_bar.isVisible())

    def test_filter_chips_clear_independently_and_keep_search(self):
        controls = self.window.file_list_controls
        controls.search_edit.setText('image1')
        controls._set_filter('annotated', 'verified', 'any', 'blur')
        self.app.processEvents()
        self.assertTrue(controls.filter_chips.isVisible())
        self.assertTrue(all(chip.isVisible() for chip in controls.chip_buttons.values()))
        controls.chip_buttons['review'].click()
        self.assertEqual(controls.state.review_filter, 'all')
        self.assertEqual(controls.filter_panel.review_combo.currentData(), 'all')
        self.assertEqual(controls.state.annotation_filter, 'annotated')
        self.assertEqual(controls.state.alert_filter, 'any')
        self.assertEqual(controls.state.quality_filter, 'blur')
        self.assertEqual(controls.state.text_filter, 'image1')
        controls.clear_chips_button.click()
        self.assertFalse(controls.state.advanced_filter_active)
        self.assertEqual(controls.state.text_filter, 'image1')
        self.assertFalse(controls.filter_chips.isVisible())

    def test_hidden_selection_is_visible_in_context_and_remains_targeted(self):
        self.select(1, 2)
        self.window.file_list_controls.search_edit.setText('image2')
        self.app.processEvents()
        self.assertEqual(self.window.file_selection_count_label.text(), '2 selected (1 hidden)')
        self.assertIn('Current hidden', self.window.file_summary_label.text())
        self.assertTrue(self.window.file_selection_bar.isVisible())
        paths = [self.window.m_img_list[1], self.window.m_img_list[2]]
        with patch.object(self.window, '_set_review_state') as review:
            self.window.file_review_actions[0].trigger()
            review.assert_called_once_with(paths, 'verified', confirm_multiple=True)

    def test_footer_menu_uses_current_selection_and_localized_actions(self):
        w = self.window
        self.select(1)
        w.populate_file_selection_menu(w.file_more_menu)
        self.assertEqual(w.file_more_menu.actions()[0].text(), 'Open')
        self.assertTrue(w.file_more_menu.actions()[0].isEnabled())
        self.select(1, 2)
        w.populate_file_selection_menu(w.file_more_menu)
        self.assertFalse(w.file_more_menu.actions()[0].isEnabled())
        self.assertIn('Batch Rename', w.file_more_menu.actions()[1].text())
        w.change_language(SIMPLIFIED_CHINESE)
        self.assertEqual(w.file_panel_title.text(), '文件列表')
        self.assertEqual(w.file_rename_button.text(), '批量重命名')
        self.assertEqual(w.file_list_controls.sort_button.text(), '文件名')
        self.assertEqual(w.file_selection_count_label.text(), '已选 2 个')

    def test_directory_row_triggers_existing_command(self):
        calls = []
        self.window.actions.changeSaveDir.triggered.connect(lambda: calls.append(True))
        with patch('labelimg.workbench.main_window.QFileDialog.getExistingDirectory', return_value='') as chooser:
            self.window.annotation_directory_bar.click()
            chooser.assert_called_once()
        self.assertEqual(calls, [True])

    def test_path_and_count_are_rendered_with_the_panel_metadata_style(self):
        label = self.window.annotation_target_label
        self.assertEqual(label.font().pixelSize(), 11)
        self.assertEqual(label.palette().windowText().color(), QColor(COLORS["muted"]))
        badge = self.window.file_summary_label
        self.assertEqual(badge.grab().toImage().pixelColor(2, badge.height() // 2), QColor(COLORS["background"]))

    def test_footer_is_disabled_with_list_during_blocked_operations(self):
        self.select(1, 2)
        self.window.file_list_widget.setEnabled(False)
        self.assertFalse(self.window.file_rename_button.isEnabled())
        self.assertFalse(self.window.file_review_button.isEnabled())
        self.assertFalse(self.window.file_more_button.isEnabled())
        self.window.file_list_widget.setEnabled(True)
        self.assertTrue(self.window.file_rename_button.isEnabled())

    def test_save_status_is_rightmost_and_independent_of_filename(self):
        delegate = self.window.file_list_widget.itemDelegate()
        self.assertIsInstance(delegate, FileListItemDelegate)
        for width in (170, 400):
            layout = delegate.row_layout(QRect(0, 0, width, 30))
            self.assertEqual(layout['alert'].right(), width - 1)
            self.assertLess(layout['name'].right(), layout['review'].left())
            self.assertLess(layout['review'].right(), layout['quality'].left())
            self.assertLess(layout['quality'].right(), layout['alert'].left())
        item = self.window.file_list_widget.item(1)
        item.setText('image_' + 'long_name_' * 50 + '_1234.png')
        item.setData(FILE_PERSISTENCE_FLAGS_ROLE, ('dirty',))
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 170, 30)
        option.state = QStyle.State_Enabled
        option.widget = self.window.file_list_widget
        image = QImage(170, 30, QImage.Format_ARGB32)
        image.fill(QColor('white'))
        painter = QPainter(image)
        delegate.paint(painter, option, self.window.file_list_widget.indexFromItem(item))
        painter.end()
        center = delegate.row_layout(option.rect)['alert'].center()
        self.assertEqual(image.pixelColor(center), QColor(COLORS["icon_annotation_tint"]))
        self.assertEqual(option.widget.textElideMode(), Qt.ElideMiddle)


if __name__ == '__main__':
    unittest.main()
