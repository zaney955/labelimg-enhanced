"""Deterministic work bounds for user gestures on large file lists."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtWidgets import QApplication
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench
from labelimg.files.ui.list_widget import FileListItem, FILE_ANNOTATION_STATE_ROLE


class InteractionPerformanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'LABELIMG_CONFIG_DIR': self.temp.name})
        self.environment.start()
        classes = os.path.join(self.temp.name, 'classes.txt')
        open(classes, 'w').close()
        self.window = create_workbench(WorkbenchLaunchOptions(class_file=classes))
        self.window.dir_name = self.temp.name
        self.window.m_img_list = [os.path.join(self.temp.name, f'{i:05}.png') for i in range(300)]
        items = []
        for i, path in enumerate(self.window.m_img_list):
            item = FileListItem(os.path.basename(path))
            item.setData(Qt.UserRole, path)
            item.setData(FILE_ANNOTATION_STATE_ROLE, 'annotated' if i % 2 else 'unannotated')
            items.append(item)
        self.list = self.window.file_list_widget
        self.list.setItems(items)
        self.window.apply_file_list_view(False)

    def tearDown(self):
        self.window.stop_directory_load()
        self.window.shutdown_image_decode_cache()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.environment.stop()
        self.temp.cleanup()

    def test_annotation_filter_evaluates_rows_once_and_preserves_hidden_selection(self):
        self.list.item(0).setSelected(True)
        self.list.item(1).setSelected(True)
        proxy = self.list._proxy_model
        with patch.object(proxy, 'filterAcceptsRow', wraps=proxy.filterAcceptsRow) as evaluate:
            self.window.file_list_controls._set_filter('annotated', 'all', 'all')
            self.assertEqual(len(self.list.visible_items()), 150)
            self.assertLessEqual(evaluate.call_count, 2 * self.list.count())
        self.assertEqual(len(self.list.selectedItems()), 2)
        self.window.file_list_controls.clear_all_conditions()
        self.assertEqual(len(self.list.selectionModel().selectedIndexes()), 2)

    def test_bulk_selection_publishes_one_final_selection(self):
        counts = []
        self.list.itemSelectionChanged.connect(lambda: counts.append(len(self.list.selectedItems())))
        self.list.select_all_visible()
        self.assertEqual(counts, [300])
        counts.clear()
        self.list.invert_visible_selection()
        self.assertEqual(counts, [0])

    def test_restoring_a_multi_selection_publishes_one_final_selection(self):
        counts = []
        self.list.itemSelectionChanged.connect(lambda: counts.append(len(self.list.selectedItems())))
        self.list._restore_selection_paths(self.window.m_img_list[::2])
        self.assertEqual(counts, [150])

    def test_group_visibility_publishes_one_summary_and_no_synchronous_repaints(self):
        from labelimg.canvas import Shape
        shapes = [Shape(label='cat') for _ in range(100)]
        self.window.canvas.load_shapes(shapes)
        self.window.label_list.set_scene(shapes)
        with patch.object(self.window.canvas, 'repaint') as repaint, \
             patch.object(self.window.label_list, '_emit_summary') as summary:
            self.window.label_visibility_requested(shapes, False)
            self.assertTrue(all(not self.window.canvas.isVisible(shape) for shape in shapes))
            self.assertEqual(summary.call_count, 1)
            repaint.assert_not_called()

    def test_deletion_reuses_remaining_rows_without_directory_rediscovery(self):
        from labelimg.files.application.operations import FileOperationResult
        before = list(self.window.m_img_list)
        survivor = self.list.item(299)
        result = FileOperationResult(succeeded_images=before[:150])
        with patch.object(self.window, 'scan_all_images', return_value=before[150:]) as scan, \
             patch.object(self.window, '_file_list_item', wraps=self.window._file_list_item) as build, \
             patch.object(self.window, 'load_file_after_deletion'):
            self.window.rebuild_file_list_after_deletion(before, None, 0, result)
            scan.assert_not_called()
            build.assert_not_called()
        self.assertIs(self.list.item(149), survivor)
        self.assertEqual(self.window.m_img_list, before[150:])

    def test_deletion_during_indexing_finishes_remaining_row_statuses(self):
        from labelimg.files.application.operations import FileOperationResult
        before = list(self.window.m_img_list)
        self.window.file_list_controls.set_index_complete(False)
        result = FileOperationResult(succeeded_images=before[:150])
        with patch.object(self.window, 'update_file_list_item_status') as refresh, \
             patch.object(self.window, 'load_file_after_deletion'):
            self.window.rebuild_file_list_after_deletion(before, None, 0, result)
        self.assertEqual({call.args[0] for call in refresh.call_args_list}, set(before[150:]))
        self.assertTrue(self.window.file_list_controls.index_complete)
