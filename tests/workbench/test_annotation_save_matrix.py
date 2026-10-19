"""Exercise real edit/save entry points against independently specified paths."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication

from labelimg.annotations.domain.model import AnnotationBox, AnnotationFormat
from labelimg.annotations.infrastructure.document import AnnotationDocument
from labelimg.annotations.infrastructure import storage
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


# image root (None means standalone), image, annotation root, new target,
# existing target. Paths intentionally do not call the production resolver.
LAYOUTS = {
    "adjacent_flat": ("data", "data/a.png", None, "data/a", "data/a"),
    "adjacent_nested": ("data", "data/类别/a.png", None, "data/类别/a", "data/类别/a"),
    "shared_flat": ("data", "data/a.png", "data", "data/a", "data/a"),
    "shared_nested": ("data", "data/类别/a.png", "data", "data/类别/a", "data/类别/a"),
    "separate_flat": ("photos", "photos/a.png", "annotations", "annotations/a", "annotations/a"),
    "separate_nested": ("photos", "photos/类别/a.png", "annotations", "annotations/类别/a", "annotations/类别/a"),
    "separate_legacy_flat": ("photos", "photos/类别/a.png", "annotations", "annotations/类别/a", "annotations/a"),
    "shared_legacy_flat": ("data", "data/类别/a.png", "data", "data/类别/a", "data/a"),
    "dataset_root": ("images", "images/train/a.png", "labels", "labels/train/a", "labels/train/a"),
    "dataset_open_split": ("images/train", "images/train/a.png", "labels", "labels/train/a", "labels/train/a"),
    "dataset_paired_split": ("images/train", "images/train/a.png", "labels/train", "labels/train/a", "labels/train/a"),
    "standalone_adjacent": (None, "data/类别/a.png", None, "data/类别/a", "data/类别/a"),
    "standalone_separate": (None, "photos/类别/a.png", "annotations", "annotations/a", "annotations/a"),
}
POINTS = ((10, 10), (40, 10), (40, 40), (10, 40))


class AnnotationSaveMatrixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(
            os.environ, {"LABELIMG_CONFIG_DIR": str(self.root / "config")}
        )
        self.environment.start()
        self.window = None
        self.image = QImage(100, 100, QImage.Format_RGB32)
        self.image.fill(0)
        self.classes = self.root / "bootstrap.names"
        self.classes.write_text("", encoding="utf8")

    def tearDown(self):
        if self.window is not None:
            self.window.auto_save_timer.stop()
            self.window.shutdown_image_decode_cache()
            self.window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()

    def write_document(self, path, annotation_format, image_path, labels=("old",)):
        path.parent.mkdir(parents=True, exist_ok=True)
        AnnotationDocument(
            image_path=str(image_path), image_data=self.image,
            boxes=tuple(AnnotationBox(label, POINTS) for label in labels),
            class_names=("old", "unused"),
        ).save(str(path), annotation_format)

    def open_workspace(self, image_path, image_root=None, save_root=None):
        self.window = create_workbench(WorkbenchLaunchOptions(
            class_file=str(self.classes), save_dir=str(save_root) if save_root else "",
        ))
        errors = patch.object(
            self.window, "error_message",
            side_effect=lambda *args: self.fail(str(args)),
        )
        errors.start()
        self.addCleanup(errors.stop)
        dialogs = patch.object(
            self.window, "save_file_dialog",
            side_effect=lambda *args: self.fail("Unexpected save-location request"),
        )
        dialogs.start()
        self.addCleanup(dialogs.stop)
        self.window.set_format(AnnotationFormat.PASCAL_VOC.display_name)
        if image_root is None:
            self.assertTrue(self.window.load_file(str(image_path)))
        else:
            self.window.import_dir_images(str(image_root))
            self.assertEqual(self.window.file_path, str(image_path))
        self.window.auto_saving.setChecked(False)

    def rename_box(self):
        with patch.object(
            self.window.candidate_label_dialog, "choose", return_value="new"
        ):
            self.window.edit_shape_label(self.window.canvas.shapes[0])

    def add_box(self):
        self.window.annotation_clipboard = [("new", POINTS, False)]
        self.window.paste_copied_bounding_boxes()

    def save(self, mode):
        if mode == "manual":
            self.window.save_file()
        else:
            self.window.auto_saving.setChecked(True)
            self.window.save_dirty_annotations()
        self.assertFalse(self.window.dirty)

    def annotation_files(self):
        return {
            path for path in self.root.rglob("*")
            if path.suffix in (".xml", ".txt", ".json")
            and path.name != "classes.txt"
        }

    def assert_labels(self, target, image_path, labels):
        document = AnnotationDocument.load(str(target), str(image_path), self.image)
        self.assertEqual([box.label for box in document.boxes], labels)

    def check_matrix_case(self, layout, annotation_format, state, mode):
        image_root, image_name, save_root, new_stem, existing_stem = LAYOUTS[layout]
        image_path = self.root / image_name
        image_path.parent.mkdir(parents=True)
        self.assertTrue(self.image.save(str(image_path)))
        target = self.root / (
            (new_stem if state == "new" else existing_stem)
            + annotation_format.extension
        )
        if save_root:
            (self.root / save_root).mkdir(parents=True, exist_ok=True)
        if state != "new":
            self.write_document(
                target, annotation_format, image_path,
                labels=() if state == "empty" else ("old",),
            )
        self.open_workspace(
            image_path, self.root / image_root if image_root else None,
            self.root / save_root if save_root else None,
        )
        if state == "new":
            self.assertFalse(self.window.canvas.shapes)
            self.window.set_annotation_format(annotation_format)
            if layout == "standalone_separate":
                with patch.object(self.window, "save_file_dialog", return_value=str(target)):
                    self.window.save_file_as()
        else:
            self.assertIs(self.window.annotation_format, annotation_format)
        if state == "rename":
            self.rename_box()
        else:
            self.add_box()
        self.save(mode)
        self.assertEqual(self.annotation_files(), {target})
        self.assert_labels(target, image_path, ["old", "new"] if state == "append" else ["new"])
        self.assertEqual(self.window.annotation_editing.view.current_target, str(target))
        if annotation_format is AnnotationFormat.YOLO:
            classes = (target.parent / "classes.txt").read_text(encoding="utf8").splitlines()
            self.assertIn("new", classes)
            if state != "new":
                self.assertEqual(classes[:2], ["old", "unused"])

    def nested_fixture(self):
        image_path = self.root / "data/类别/a.png"
        image_path.parent.mkdir(parents=True)
        self.assertTrue(self.image.save(str(image_path)))
        return image_path, self.root / "data"

    def check_format_switch(self, source, destination, mode):
        image_path, directory = self.nested_fixture()
        original = image_path.with_suffix(source.extension)
        self.write_document(original, source, image_path)
        original_bytes = original.read_bytes()
        self.open_workspace(image_path, directory, directory)
        self.window.set_annotation_format(destination)
        self.add_box()
        self.save(mode)
        target = image_path.with_suffix(destination.extension)
        self.assertEqual(self.annotation_files(), {original, target})
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assert_labels(target, image_path, ["old", "new"])

    def check_document_choice(self, selected_format, mode, same_format=False):
        image_path, directory = self.nested_fixture()
        paths = []
        for annotation_format in AnnotationFormat:
            if same_format and annotation_format is not selected_format:
                continue
            target = image_path.with_suffix(annotation_format.extension)
            self.write_document(target, annotation_format, image_path)
            paths.append(target)
        if same_format:
            flat = directory / ("a" + selected_format.extension)
            self.write_document(flat, selected_format, image_path)
            paths.append(flat)
        chosen = paths[-1] if same_format else image_path.with_suffix(selected_format.extension)
        original = {path: path.read_bytes() for path in paths}

        def choose(*args):
            labels = args[3]
            return next(label for label in labels if str(chosen) in label), True

        with patch("labelimg.workbench.main_window.QInputDialog.getItem", side_effect=choose) as prompt:
            self.open_workspace(image_path, directory, directory)
        prompt.assert_called_once()
        self.assertIs(self.window.annotation_format, selected_format)
        self.rename_box()
        self.save(mode)
        self.assertEqual(self.annotation_files(), set(paths))
        self.assert_labels(chosen, image_path, ["new"])
        for path in paths:
            if path != chosen:
                self.assertEqual(path.read_bytes(), original[path])

    def check_save_as(self, annotation_format, mode):
        image_path, directory = self.nested_fixture()
        original = image_path.with_suffix(annotation_format.extension)
        self.write_document(original, annotation_format, image_path)
        original_bytes = original.read_bytes()
        self.open_workspace(image_path, directory, directory)
        chosen = self.root / "chosen" / ("renamed" + annotation_format.extension)
        self.rename_box()
        with patch.object(self.window, "save_file_dialog", return_value=str(chosen)):
            self.window.save_file_as()
        self.add_box()
        self.save(mode)
        self.assertEqual(self.annotation_files(), {chosen, original})
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assert_labels(chosen, image_path, ["new", "new"])

    def check_duplicate_names(self, annotation_format, existing):
        first = self.root / "data/left/a.png"
        second = self.root / "data/right/a.png"
        for image_path in (first, second):
            image_path.parent.mkdir(parents=True)
            self.assertTrue(self.image.save(str(image_path)))
            if existing:
                self.write_document(
                    image_path.with_suffix(annotation_format.extension),
                    annotation_format, image_path,
                )
        choices = patch(
            "labelimg.workbench.main_window.QInputDialog.getItem",
            side_effect=lambda *args: self.fail("Independent sidecars must not require a document choice"),
        )
        choices.start()
        self.addCleanup(choices.stop)
        self.open_workspace(first, self.root / "data", self.root / "data")
        if not existing:
            self.window.set_annotation_format(annotation_format)
        self.add_box()
        self.save("manual")
        self.assertTrue(self.window.load_file(str(second)))
        self.assertEqual(
            [shape.label for shape in self.window.canvas.shapes],
            ["old"] if existing else [],
        )
        self.add_box()
        self.save("manual")
        expected = {path.with_suffix(annotation_format.extension) for path in (first, second)}
        self.assertEqual(self.annotation_files(), expected)
        for image_path in (first, second):
            self.assert_labels(
                image_path.with_suffix(annotation_format.extension), image_path,
                ["old", "new"] if existing else ["new"],
            )

    def check_shared_collection(self, state, mode):
        image_path, directory = self.nested_fixture()
        collection = directory / "annotations.json"
        record = {
            "image": "类别/a.png", "annotations": [{
                "label": "old", "coordinates": {"x": 25, "y": 25, "width": 30, "height": 30},
            }],
        }
        peer = {"image": "peer.png", "annotations": []}
        collection.write_text(json.dumps(
            [peer] if state == "missing" else [record, peer]
        ), encoding="utf8")
        original = collection.read_bytes()
        self.open_workspace(image_path, directory, directory)
        if state == "missing":
            self.window.set_annotation_format(AnnotationFormat.CREATE_ML)
        if state == "rename":
            self.rename_box()
        else:
            self.add_box()
        self.save(mode)
        if state == "missing":
            target = image_path.with_suffix(".json")
            self.assertEqual(collection.read_bytes(), original)
            self.assert_labels(target, image_path, ["new"])
            self.assertEqual(self.annotation_files(), {collection, target})
        else:
            self.assertEqual(self.annotation_files(), {collection})
            self.assert_labels(collection, image_path, ["new"] if state == "rename" else ["old", "new"])
            records = json.loads(collection.read_text(encoding="utf8"))
            self.assertEqual(records[1], peer)
            self.assertEqual(records[0]["image"], "类别/a.png")

    def check_sidecar_outside_selected_root(self, annotation_format, mode):
        image_path, directory = self.nested_fixture()
        sidecar = image_path.with_suffix(annotation_format.extension)
        self.write_document(sidecar, annotation_format, image_path)
        original = sidecar.read_bytes()
        annotations = self.root / "annotations"
        annotations.mkdir()
        self.open_workspace(image_path, directory, annotations)
        self.assertFalse(self.window.canvas.shapes)
        self.window.set_annotation_format(annotation_format)
        self.add_box()
        self.save(mode)
        target = annotations / "类别" / ("a" + annotation_format.extension)
        self.assertEqual(self.annotation_files(), {sidecar, target})
        self.assertEqual(sidecar.read_bytes(), original)
        self.assert_labels(target, image_path, ["new"])

    def check_empty_save(self, annotation_format, existing):
        image_path, directory = self.nested_fixture()
        target = image_path.with_suffix(annotation_format.extension)
        if existing:
            self.write_document(target, annotation_format, image_path)
        self.open_workspace(image_path, directory, directory)
        if existing:
            self.window.canvas.select_shape(self.window.canvas.shapes[0])
            self.window.delete_selected_shape()
        else:
            self.window.set_annotation_format(annotation_format)
            self.window.set_dirty()
        self.save("manual")
        if annotation_format is AnnotationFormat.PASCAL_VOC:
            self.assertFalse(target.exists())
        else:
            self.assert_labels(target, image_path, [])

    def check_yolo_fallback_mapping(self, source, existing):
        image_path = self.root / "images/train/a.png"
        image_path.parent.mkdir(parents=True)
        self.assertTrue(self.image.save(str(image_path)))
        target = self.root / "labels/train/a.txt"
        target.parent.mkdir(parents=True)
        mapping = self.root / ("labels/classes.txt" if source == "classes" else "data.yaml")
        mapping.write_text(
            "old\nunused\n" if source == "classes" else "names: [old, unused]\n",
            encoding="utf8",
        )
        original = mapping.read_bytes()
        if existing:
            target.write_text("0 0.25 0.25 0.3 0.3\n", encoding="utf8")
        self.open_workspace(image_path, self.root / "images", self.root / "labels")
        if not existing:
            self.window.set_annotation_format(AnnotationFormat.YOLO)
        self.add_box()
        self.save("manual")
        if source == "yaml":
            self.assertEqual(mapping.read_bytes(), original)
        else:
            self.assertEqual(mapping.read_text(encoding="utf8").splitlines(), ["old", "unused", "new"])
        self.assertEqual(
            (target.parent / "classes.txt").read_text(encoding="utf8").splitlines(),
            ["old", "unused", "new"],
        )
        self.assert_labels(target, image_path, ["old", "new"] if existing else ["new"])

    def test_cancelling_document_choice_keeps_all_files_unchanged(self):
        image_path, directory = self.nested_fixture()
        for annotation_format in AnnotationFormat:
            self.write_document(image_path.with_suffix(annotation_format.extension), annotation_format, image_path)
        original = {path: path.read_bytes() for path in self.annotation_files()}
        with patch("labelimg.workbench.main_window.QInputDialog.getItem", return_value=("", False)):
            self.window = create_workbench(WorkbenchLaunchOptions(
                class_file=str(self.classes), save_dir=str(directory),
            ))
            self.assertFalse(self.window.import_dir_images(str(directory)))
        self.assertIsNone(self.window.file_path)
        self.assertEqual({path: path.read_bytes() for path in self.annotation_files()}, original)

    def test_repeated_yolo_saves_keep_files_writable_and_watches_active(self):
        image_path, directory = self.nested_fixture()
        target = image_path.with_suffix(".txt")
        self.write_document(target, AnnotationFormat.YOLO, image_path)
        self.open_workspace(image_path, directory, directory)
        for index in range(50):
            label = f"class-{index % 2}"
            with patch.object(self.window.candidate_label_dialog, "choose", return_value=label):
                self.window.edit_shape_label(self.window.canvas.shapes[0])
            self.save("manual")
            self.assert_labels(target, image_path, [label])
            watched = self.window._annotation_file_watcher.files()
            self.assertIn(str(target), watched)
            self.assertIn(str(target.parent / "classes.txt"), watched)

    def test_standalone_autosave_waits_for_an_explicit_destination(self):
        image_path, _directory = self.nested_fixture()
        annotations = self.root / "annotations"
        annotations.mkdir()
        self.open_workspace(image_path, save_root=annotations)
        self.add_box()
        with patch.object(self.window, "save_file_dialog") as dialog:
            self.window.auto_saving.setChecked(True)
            self.window.save_dirty_annotations()
        dialog.assert_not_called()
        self.assertFalse(self.annotation_files())
        self.assertTrue(self.window.dirty)

    def test_standalone_first_manual_save_uses_the_explicit_destination(self):
        image_path, _directory = self.nested_fixture()
        annotations = self.root / "annotations"
        annotations.mkdir()
        self.open_workspace(image_path, save_root=annotations)
        self.add_box()
        chosen = annotations / "类别/a.xml"
        with patch.object(self.window, "save_file_dialog", return_value=str(chosen)) as dialog:
            self.window.save_file()
        dialog.assert_called_once()
        self.assertEqual(self.annotation_files(), {chosen})
        self.assert_labels(chosen, image_path, ["new"])

    def test_save_destination_is_visible_and_tracks_save_as_and_format(self):
        image_path, directory = self.nested_fixture()
        self.open_workspace(image_path, directory, directory)
        self.assertIn("a.xml", self.window.annotation_target_label.text())
        self.assertIn(str(image_path.with_suffix(".xml")), self.window.annotation_target_label.toolTip())
        self.window.set_annotation_format(AnnotationFormat.CREATE_ML)
        self.assertIn("a.json", self.window.annotation_target_label.text())
        self.add_box()
        chosen = self.root / "chosen.json"
        with patch.object(self.window, "save_file_dialog", return_value=str(chosen)):
            self.window.save_file_as()
        self.assertIn("chosen.json", self.window.annotation_target_label.text())
        self.assertIn(str(chosen), self.window.annotation_target_label.toolTip())

    def check_cancel_first_save(self, annotation_format):
        image_path, _directory = self.nested_fixture()
        annotations = self.root / "annotations"
        annotations.mkdir()
        self.open_workspace(image_path, save_root=annotations)
        self.window.set_annotation_format(annotation_format)
        self.add_box()
        with patch.object(self.window, "save_file_dialog", return_value=""):
            self.window.save_file()
        self.assertTrue(self.window.dirty)
        self.assertFalse(self.annotation_files())
        with patch.object(self.window, "save_file_dialog") as dialog:
            self.window.auto_saving.setChecked(True)
            self.window.save_dirty_annotations()
        dialog.assert_not_called()
        self.assertFalse(self.annotation_files())

    def check_cancel_save_as(self, annotation_format):
        image_path, directory = self.nested_fixture()
        original = image_path.with_suffix(annotation_format.extension)
        self.write_document(original, annotation_format, image_path)
        before = original.read_bytes()
        self.open_workspace(image_path, directory, directory)
        self.rename_box()
        with patch.object(self.window, "save_file_dialog", return_value=""):
            self.window.save_file_as()
        self.assertTrue(self.window.dirty)
        self.assertEqual(self.annotation_files(), {original})
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(self.window._current_annotation_target(), str(original))

    def check_failed_save_as(self, annotation_format):
        image_path, directory = self.nested_fixture()
        original = image_path.with_suffix(annotation_format.extension)
        self.write_document(original, annotation_format, image_path)
        before = original.read_bytes()
        self.open_workspace(image_path, directory, directory)
        self.rename_box()
        chosen = self.root / "chosen" / ("a" + annotation_format.extension)
        with patch.object(self.window, "save_file_dialog", return_value=str(chosen)), patch.object(
            self.window, "error_message"
        ) as error, patch.object(storage, "_atomic_commit_staged", side_effect=OSError("injected write failure")):
            self.window.save_file_as()
        error.assert_called_once()
        self.assertTrue(self.window.dirty)
        self.assertFalse(chosen.exists())
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(self.window._current_annotation_target(), str(chosen))
        self.save("manual")
        self.assertEqual(original.read_bytes(), before)
        self.assert_labels(chosen, image_path, ["new"])

    def check_failed_first_save_retries_the_chosen_destination(self, annotation_format):
        image_path, _directory = self.nested_fixture()
        annotations = self.root / "annotations"
        annotations.mkdir()
        self.open_workspace(image_path, save_root=annotations)
        self.window.set_annotation_format(annotation_format)
        self.add_box()
        chosen = annotations / "类别" / ("a" + annotation_format.extension)
        with patch.object(self.window, "save_file_dialog", return_value=str(chosen)), patch.object(
            self.window, "error_message"
        ), patch.object(storage, "_atomic_commit_staged", side_effect=OSError("injected write failure")):
            self.window.save_file()
        self.assertTrue(self.window.dirty)
        self.assertEqual(self.window._current_annotation_target(), str(chosen))
        self.assertIn(str(chosen), self.window.annotation_target_label.toolTip())
        self.save("autosave")
        self.assertEqual(self.annotation_files(), {chosen})
        self.assert_labels(chosen, image_path, ["new"])

    def check_conversion_overwrite_requires_confirmation(self, source, destination):
        image_path, directory = self.nested_fixture()
        original = image_path.with_suffix(source.extension)
        target = image_path.with_suffix(destination.extension)
        self.write_document(original, source, image_path)
        self.write_document(target, destination, image_path, labels=("other",))
        before = {path: path.read_bytes() for path in (original, target)}
        with patch(
            "labelimg.workbench.main_window.QInputDialog.getItem",
            side_effect=lambda *args: (next(label for label in args[3] if str(original) in label), True),
        ):
            self.open_workspace(image_path, directory, directory)
        self.window.set_annotation_format(destination)
        self.add_box()
        with patch.object(self.window, "save_file_dialog") as dialog:
            self.window.auto_saving.setChecked(True)
            self.window.save_dirty_annotations()
        dialog.assert_not_called()
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        with patch.object(self.window, "save_file_dialog", return_value=""):
            self.window.save_file()
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        with patch.object(self.window, "save_file_dialog", return_value=str(target)):
            self.window.save_file()
        self.assertEqual(original.read_bytes(), before[original])
        self.assert_labels(target, image_path, ["old", "new"])
        self.assertFalse(self.window.dirty)

    def test_batch_save_cannot_bypass_standalone_destination_selection(self):
        image_path, _directory = self.nested_fixture()
        annotations = self.root / "annotations"
        annotations.mkdir()
        self.open_workspace(image_path, save_root=annotations)
        self.add_box()
        view = self.window.annotation_editing.view
        with patch.object(self.window, "save_file_dialog", return_value=""):
            self.assertIsNone(self.window._save_history_views((view,)))
        self.assertFalse(self.annotation_files())
        chosen = annotations / "类别/a.xml"
        with patch.object(self.window, "save_file_dialog", return_value=str(chosen)):
            self.assertIsNotNone(self.window._save_history_views((view,)))
        self.assertEqual(self.annotation_files(), {chosen})
        self.assert_labels(chosen, image_path, ["new"])

    def test_batch_first_save_preserves_each_images_format(self):
        first, _directory = self.nested_fixture()
        second = first.with_name("b.png")
        self.assertTrue(self.image.save(str(second)))
        annotations = self.root / "annotations"
        annotations.mkdir()
        self.open_workspace(first, save_root=annotations)
        self.window.set_annotation_format(AnnotationFormat.YOLO)
        self.add_box()
        self.assertTrue(self.window.load_file(str(second)))
        self.window.set_annotation_format(AnnotationFormat.PASCAL_VOC)
        self.add_box()
        first_target = annotations / "a.txt"
        second_target = annotations / "b.xml"
        with patch.object(self.window, "save_file_dialog", return_value=str(second_target)), patch(
            "labelimg.workbench.main_window.QFileDialog.getSaveFileName", return_value=(str(first_target), "")
        ):
            result = self.window._save_history_views(self.window.annotation_editing.dirty_views())
        self.assertIsNotNone(result)
        self.assertEqual(self.annotation_files(), {first_target, second_target})
        self.assert_labels(first_target, first, ["new"])
        self.assert_labels(second_target, second, ["new"])


def matrix_test(layout, annotation_format, state, mode):
    def test(self):
        self.check_matrix_case(layout, annotation_format, state, mode)
    return test


for _layout in LAYOUTS:
    for _format in AnnotationFormat:
        for _state in ("new", "rename", "append", "empty"):
            for _mode in ("manual", "autosave"):
                setattr(
                    AnnotationSaveMatrixTest,
                    f"test_{_layout}_{_format.name.lower()}_{_state}_{_mode}",
                    matrix_test(_layout, _format, _state, _mode),
                )


def scenario_test(method, *args):
    def test(self):
        getattr(self, method)(*args)
    return test


for _source in AnnotationFormat:
    for _scenario in ("cancel_first_save", "cancel_save_as", "failed_save_as", "failed_first_save_retries_the_chosen_destination"):
        setattr(AnnotationSaveMatrixTest, f"test_{_scenario}_{_source.name}",
            scenario_test("check_" + _scenario, _source))
    for _destination in AnnotationFormat:
        if _source is not _destination:
            setattr(AnnotationSaveMatrixTest, f"test_confirm_conversion_{_source.name}_{_destination.name}",
                scenario_test("check_conversion_overwrite_requires_confirmation", _source, _destination))
    for _mode in ("manual", "autosave"):
        for _destination in AnnotationFormat:
            if _source is not _destination:
                setattr(AnnotationSaveMatrixTest,
                    f"test_convert_{_source.name}_{_destination.name}_{_mode}",
                    scenario_test("check_format_switch", _source, _destination, _mode))
        for _same in (False, True):
            setattr(AnnotationSaveMatrixTest,
                f"test_choose_{_source.name}_{_mode}_same_format_{_same}",
                scenario_test("check_document_choice", _source, _mode, _same))
        setattr(AnnotationSaveMatrixTest, f"test_save_as_{_source.name}_{_mode}",
            scenario_test("check_save_as", _source, _mode))
        setattr(AnnotationSaveMatrixTest, f"test_other_root_{_source.name}_{_mode}",
            scenario_test("check_sidecar_outside_selected_root", _source, _mode))
    for _existing in (False, True):
        setattr(AnnotationSaveMatrixTest, f"test_duplicates_{_source.name}_{_existing}",
            scenario_test("check_duplicate_names", _source, _existing))
        setattr(AnnotationSaveMatrixTest, f"test_empty_save_{_source.name}_{_existing}",
            scenario_test("check_empty_save", _source, _existing))

for _state in ("rename", "append", "missing"):
    for _mode in ("manual", "autosave"):
        setattr(AnnotationSaveMatrixTest, f"test_collection_{_state}_{_mode}",
            scenario_test("check_shared_collection", _state, _mode))

for _source in ("classes", "yaml"):
    for _existing in (False, True):
        setattr(AnnotationSaveMatrixTest, f"test_yolo_mapping_{_source}_{_existing}",
            scenario_test("check_yolo_fallback_mapping", _source, _existing))


if __name__ == "__main__":
    unittest.main()
