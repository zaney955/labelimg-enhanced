import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication, QListWidgetItem

from labelimg.files.ui.list_widget import (
    FILE_ANNOTATION_STATE_ROLE,
    FILE_PERSISTENCE_FLAGS_ROLE,
    FILE_REVIEW_STATE_ROLE,
    FileListControlBar,
    FileListViewState,
    FileListWidget,
)
from labelimg.files.model import (
    FileListItemState,
    FileListProjection,
    FileListQuery,
)
from labelimg.platform.settings_keys import (
    SETTING_FILE_LIST_SORT_DESCENDING,
    SETTING_FILE_LIST_SORT_KEY,
)
from labelimg.platform.settings import Settings
from labelimg.localization.runtime import SIMPLIFIED_CHINESE, set_language


class FileListViewStateTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = self.temporary.name
        self.paths = [
            os.path.join(self.root, "day2", "2.png"),
            os.path.join(self.root, "day1", "10.png"),
            os.path.join(self.root, "day2", "1.png"),
            os.path.join(self.root, "day1", "2.png"),
        ]
        self.annotation = {
            self.paths[0]: "annotated",
            self.paths[1]: "unannotated",
            self.paths[2]: "annotated",
            self.paths[3]: "unannotated",
        }
        self.review = {
            self.paths[0]: "verified",
            self.paths[1]: "questioned",
            self.paths[2]: "unreviewed",
            self.paths[3]: "questioned",
        }
        self.modified = {
            self.paths[0]: 20,
            self.paths[1]: 10,
            self.paths[2]: 20,
            self.paths[3]: 10,
        }
        self.flags = {
            self.paths[0]: (),
            self.paths[1]: ("dirty",),
            self.paths[2]: (),
            self.paths[3]: ("conflict",),
        }

    def tearDown(self):
        self.temporary.cleanup()

    def ordered(self, state):
        return list(state.project(
            self.paths,
            self.root,
            annotation_state_for=self.annotation.get,
            review_state_for=self.review.get,
            persistence_flags_for=lambda _path: (),
            modified_time_for=self.modified.get,
        ).ordered_paths)

    def visible(self, state):
        return list(state.project(
            self.paths,
            self.root,
            annotation_state_for=self.annotation.get,
            review_state_for=self.review.get,
            persistence_flags_for=self.flags.get,
        ).visible_paths)

    def test_name_order_keeps_relative_directories_as_natural_batches(self):
        state = FileListViewState("name", False)
        self.assertEqual(
            [os.path.relpath(path, self.root) for path in self.ordered(state)],
            [
                os.path.join("day1", "2.png"),
                os.path.join("day1", "10.png"),
                os.path.join("day2", "1.png"),
                os.path.join("day2", "2.png"),
            ],
        )

        state.descending = True
        self.assertEqual(
            [os.path.relpath(path, self.root) for path in self.ordered(state)],
            [
                os.path.join("day2", "2.png"),
                os.path.join("day2", "1.png"),
                os.path.join("day1", "10.png"),
                os.path.join("day1", "2.png"),
            ],
        )

    def test_state_and_modified_time_sorts_use_stable_batch_ties(self):
        annotation = FileListViewState("annotation", False)
        self.assertEqual(
            [os.path.relpath(path, self.root) for path in self.ordered(annotation)],
            [
                os.path.join("day1", "2.png"),
                os.path.join("day1", "10.png"),
                os.path.join("day2", "1.png"),
                os.path.join("day2", "2.png"),
            ],
        )

        review = FileListViewState("review", False)
        self.assertEqual(
            [self.review[path] for path in self.ordered(review)],
            ["unreviewed", "questioned", "questioned", "verified"],
        )

        modified = FileListViewState("modified", True)
        self.assertEqual(
            self.ordered(modified)[:2],
            [self.paths[2], self.paths[0]],
        )

    def test_filters_are_conjunctive_and_match_relative_path_separators(self):
        state = FileListViewState()
        state.set_filter(
            text=" DAY1/ ",
            annotation="unannotated",
            review="questioned",
            alert="any",
        )
        self.assertEqual(
            self.visible(state),
            [self.paths[3], self.paths[1]],
        )
        self.assertTrue(state.filter_active)

        state.reset_filter()
        self.assertEqual(self.visible(state), self.ordered(state))
        self.assertFalse(state.filter_active)

    def test_quality_filter_is_independent_from_persistence_alerts(self):
        state = FileListViewState()
        state.set_filter(quality="issues")
        issues = {self.paths[0]: ("blur",), self.paths[2]: ("dark",)}

        visible = state.project(
            self.paths,
            self.root,
            annotation_state_for=self.annotation.get,
            review_state_for=self.review.get,
            persistence_flags_for=self.flags.get,
            quality_findings_for=lambda path: issues.get(path, ()),
        ).visible_paths

        self.assertEqual(visible, (self.paths[2], self.paths[0]))
        self.assertEqual(state.alert_filter, "all")
        self.assertEqual(state.quality_filter, "issues")

        state.set_filter(quality="warning")
        structured = {
            self.paths[1]: ({"code": "blur", "severity": "warning"},),
            self.paths[3]: ({"code": "unreadable", "severity": "error"},),
        }
        self.assertEqual(
            state.project(
                self.paths,
                self.root,
                annotation_state_for=self.annotation.get,
                review_state_for=self.review.get,
                persistence_flags_for=self.flags.get,
                quality_findings_for=lambda path: structured.get(path, ()),
            ).visible_paths,
            (self.paths[1],),
        )


class FileListProjectionTest(unittest.TestCase):
    def test_one_projection_owns_order_filter_and_visible_navigation(self):
        root = os.path.abspath("workspace")
        first = FileListItemState(
            os.path.join(root, "day2", "10.png"),
            modified_time=20,
            annotation_state="annotated",
            review_state="verified",
        )
        second = FileListItemState(
            os.path.join(root, "day1", "2.png"),
            modified_time=10,
            annotation_state="unannotated",
            review_state="questioned",
            persistence_flags=("dirty",),
        )
        third = FileListItemState(
            os.path.join(root, "day2", "1.png"),
            modified_time=30,
            annotation_state="annotated",
            review_state="unreviewed",
            quality_findings=({"code": "blur", "severity": "warning"},),
        )

        projection = FileListProjection.create(
            root,
            (first, second, third),
            FileListQuery(
                sort_key="name",
                text="day2/",
                annotation="annotated",
            ),
        )

        self.assertEqual(
            projection.ordered_paths,
            (second.path, third.path, first.path),
        )
        self.assertEqual(projection.visible_paths, (third.path, first.path))
        self.assertEqual(projection.adjacent_visible(third.path, 1), first.path)
        self.assertIsNone(projection.adjacent_visible(first.path, 1))
        self.assertTrue(projection.filter_active)


class FileListControlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language(SIMPLIFIED_CHINESE)

    def tearDown(self):
        if hasattr(self, "widget"):
            self.widget.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def test_control_bar_exposes_sort_and_live_filter_state(self):
        self.widget = FileListControlBar("name", False)
        self.widget.show()
        self.app.processEvents()

        self.assertEqual(self.widget.sort_button.size().width(), 28)
        self.assertEqual(self.widget.filter_button.size().height(), 28)
        self.assertIn("文件名", self.widget.sort_button.toolTip())
        self.assertFalse(self.widget.filter_button.isEnabled())

        self.widget.sort_actions["review"].trigger()
        self.widget.descending_action.trigger()
        self.assertEqual(self.widget.state.sort_key, "review")
        self.assertTrue(self.widget.state.descending)
        self.assertIn("复核状态", self.widget.sort_button.toolTip())
        self.assertIn("降序", self.widget.sort_button.toolTip())
        self.widget.reset_sort()
        self.assertEqual(self.widget.state.sort_key, "name")
        self.assertFalse(self.widget.state.descending)

        changes = []
        self.widget.viewChanged.connect(lambda: changes.append(True))
        self.widget.set_workspace_available(True)
        self.widget.filter_panel.text_edit.setText("day1")
        self.widget.filter_panel.annotation_combo.setCurrentIndex(2)
        self.app.processEvents()

        self.assertTrue(self.widget.state.filter_active)
        self.assertTrue(self.widget.filter_button.active)
        self.assertEqual(self.widget.state.text_filter, "day1")
        self.assertEqual(self.widget.state.annotation_filter, "annotated")
        self.assertTrue(changes)

        self.widget.clear_filters()
        self.assertFalse(self.widget.state.filter_active)
        self.assertFalse(self.widget.filter_button.active)

    def test_visible_selection_commands_replace_hidden_selection(self):
        self.widget = FileListWidget()
        for index in range(4):
            item = QListWidgetItem(str(index))
            item.setData(FILE_ANNOTATION_STATE_ROLE, "annotated")
            item.setData(FILE_REVIEW_STATE_ROLE, "unreviewed")
            item.setData(FILE_PERSISTENCE_FLAGS_ROLE, ())
            self.widget.addItem(item)
        self.widget.item(0).setHidden(True)
        self.widget.item(0).setSelected(True)

        self.widget.select_all_visible()
        self.assertEqual(
            [item.text() for item in self.widget.selectedItems()],
            ["1", "2", "3"],
        )

        self.widget.item(1).setSelected(False)
        self.widget.invert_visible_selection()
        self.assertEqual(
            [item.text() for item in self.widget.selectedItems()],
            ["1"],
        )

    def test_main_window_loads_and_saves_sort_preference_only(self):
        from labelimg.workbench.bootstrap import (
            WorkbenchLaunchOptions,
            create_workbench,
        )

        with tempfile.TemporaryDirectory() as config_dir:
            with patch.dict(
                os.environ,
                {"LABELIMG_CONFIG_DIR": config_dir},
            ):
                settings = Settings()
                settings[SETTING_FILE_LIST_SORT_KEY] = "review"
                settings[SETTING_FILE_LIST_SORT_DESCENDING] = True
                self.assertTrue(settings.save())
                classes = os.path.join(config_dir, "classes.txt")
                with open(classes, "w", encoding="utf8"):
                    pass
                window = create_workbench(WorkbenchLaunchOptions(
                    class_file=classes,
                ))
                self.assertEqual(
                    window.file_list_controls.state.sort_key,
                    "review",
                )
                self.assertTrue(
                    window.file_list_controls.state.descending
                )
                window.file_list_controls.state.set_filter(text="hidden")
                window.file_list_controls.reset_sort()
                window.close()
                self.app.processEvents()

                loaded = Settings()
                self.assertTrue(loaded.load())
                self.assertEqual(
                    loaded.get(SETTING_FILE_LIST_SORT_KEY),
                    "name",
                )
                self.assertFalse(
                    loaded.get(SETTING_FILE_LIST_SORT_DESCENDING)
                )
                self.assertNotIn("fileList/filter", loaded.data)
                window.deleteLater()


if __name__ == "__main__":
    unittest.main()
