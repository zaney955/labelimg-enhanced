import os
import json
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from PyQt5.QtGui import QImage

from labelimg.annotations.domain.model import (
    AnnotationBox,
    AnnotationDocumentError,
    AnnotationFormat,
    AnnotationStatus,
)
from labelimg.annotations.infrastructure.document import AnnotationDocument
from labelimg.annotations.application.workspace import (
    AmbiguousAnnotationDocuments,
    AnnotationWorkspace,
)
from labelimg.annotations.infrastructure.storage import AnnotationStorageConflict


class AnnotationWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.image_path = os.path.abspath("tests/test.512.512.bmp")
        self.image = QImage(self.image_path)

    def document(self, label="cat", verified=False, questioned=False):
        return AnnotationDocument(
            image_path=self.image_path,
            image_data=self.image,
            boxes=(
                AnnotationBox(
                    label,
                    ((10, 20), (110, 20), (110, 120), (10, 120)),
                ),
            ),
            class_names=(label,),
            verified=verified,
            questioned=questioned,
        )

    def test_entry_resolves_all_format_paths_in_save_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = AnnotationWorkspace(save_dir=directory)
            entry = workspace.entry(self.image_path)

        self.assertEqual(
            entry.path_for(AnnotationFormat.PASCAL_VOC),
            os.path.join(directory, "test.512.512.xml"),
        )
        self.assertEqual(
            tuple(os.path.splitext(path)[1] for path in entry.paths),
            (".xml", ".txt", ".json"),
        )

    def test_entry_aggregates_status_across_real_format_adapters(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = AnnotationWorkspace(save_dir=directory)
            voc_path = workspace.entry(self.image_path).path_for(
                AnnotationFormat.PASCAL_VOC
            )
            self.document(
                verified=True,
            ).save(
                os.path.splitext(voc_path)[0],
                AnnotationFormat.PASCAL_VOC,
            )
            status = workspace.entry(self.image_path).status

        self.assertTrue(status.has_annotations)
        self.assertTrue(status.verified)
        self.assertEqual(status.labels, frozenset({"cat"}))

    @patch("locale.getpreferredencoding", return_value="cp936")
    def test_yolo_save_migrates_legacy_locale_classes_to_utf8(
        self,
        _preferred_encoding,
    ):
        label = "中文类别"
        with tempfile.TemporaryDirectory() as directory:
            workspace = AnnotationWorkspace(save_dir=directory)
            annotation_path = workspace.entry(self.image_path).path_for(
                AnnotationFormat.YOLO
            )
            classes_path = os.path.join(directory, "classes.txt")
            with open(classes_path, "wb") as classes_file:
                classes_file.write((label + "\n").encode("cp936"))
            with open(annotation_path, "w", encoding="utf8") as output:
                output.write("0 0.5 0.5 0.2 0.2\n")

            legacy_document = AnnotationDocument.load(
                annotation_path,
                self.image_path,
                self.image,
            )
            legacy_status = AnnotationDocument.inspect(annotation_path)

            saved = workspace.save(
                self.document(label),
                AnnotationFormat.YOLO,
            )

            with open(classes_path, "rb") as classes_file:
                saved_classes = classes_file.read()
            loaded = AnnotationDocument.load(
                saved.annotation_path,
                self.image_path,
                self.image,
            )

        self.assertEqual(legacy_document.boxes[0].label, label)
        self.assertEqual(legacy_status.labels, frozenset({label}))
        self.assertEqual(saved_classes.decode("utf8").splitlines(), [label])
        self.assertEqual(loaded.boxes[0].label, label)

    def test_failed_yolo_class_encoding_removes_staging_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = AnnotationWorkspace(save_dir=directory)

            with self.assertRaises(AnnotationDocumentError):
                workspace.save(
                    self.document("invalid-\ud800"),
                    AnnotationFormat.YOLO,
                )

            self.assertEqual(os.listdir(directory), [])

    def test_scan_record_and_delete_keep_candidate_labels_consistent(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = AnnotationWorkspace(save_dir=directory)
            annotation_path = workspace.entry(
                self.image_path
            ).path_for(AnnotationFormat.PASCAL_VOC)
            self.document("discovered").save(
                os.path.splitext(annotation_path)[0],
                AnnotationFormat.PASCAL_VOC,
            )

            workspace.scan(directory)
            self.assertEqual(
                workspace.candidate_labels,
                ("discovered",),
            )

            workspace.record(annotation_path, ("saved",))
            self.assertEqual(
                workspace.candidate_labels,
                ("saved",),
            )

            workspace.delete(self.image_path, remover=os.remove)
            self.assertFalse(os.path.exists(annotation_path))
            self.assertEqual(workspace.candidate_labels, ())

    def test_scan_ignores_non_annotation_text_files(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(
                os.path.join(directory, "classes.txt"),
                "w",
                encoding="utf8",
            ) as class_file:
                class_file.write("not-a-candidate\n")
            with open(
                os.path.join(directory, "readme.txt"),
                "w",
                encoding="utf8",
            ) as text_file:
                text_file.write("0 this is ordinary text\n")

            workspace = AnnotationWorkspace()
            workspace.scan(directory)

        self.assertEqual(workspace.candidate_labels, ())

    def test_scan_discovers_labels_from_valid_yolo_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(
                os.path.join(directory, "classes.txt"),
                "w",
                encoding="utf8",
            ) as class_file:
                class_file.write("cat\ndog\n")
            with open(
                os.path.join(directory, "sample.txt"),
                "w",
                encoding="utf8",
            ) as annotation_file:
                annotation_file.write("1 0.5 0.5 0.25 0.25\n")

            workspace = AnnotationWorkspace()
            workspace.scan(directory)

        self.assertEqual(workspace.candidate_labels, ("dog",))

    def test_questioned_status_takes_precedence_when_formats_disagree(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = AnnotationWorkspace(save_dir=directory)
            entry = workspace.entry(self.image_path)
            for annotation_format in (
                AnnotationFormat.PASCAL_VOC,
                AnnotationFormat.CREATE_ML,
            ):
                with open(
                    entry.path_for(annotation_format),
                    "w",
                    encoding="utf8",
                ):
                    pass
            with patch(
                "labelimg.annotations.application.workspace.AnnotationDocument.inspect",
                side_effect=(
                    AnnotationStatus(
                        True,
                        True,
                        False,
                        frozenset({"cat"}),
                    ),
                    AnnotationStatus(
                        True,
                        False,
                        True,
                        frozenset({"dog"}),
                    ),
                ),
            ):
                status = workspace.entry(self.image_path).status

        self.assertFalse(status.verified)
        self.assertTrue(status.questioned)
        self.assertEqual(status.labels, frozenset({"cat", "dog"}))

    def test_save_and_load_for_image_cover_the_document_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = AnnotationWorkspace(save_dir=directory)

            saved = workspace.save(
                self.document("saved", verified=True),
                AnnotationFormat.PASCAL_VOC,
                revision_id=41,
            )
            loaded = workspace.load_for_image(
                self.image_path,
                self.image,
            )

        self.assertFalse(saved.removed)
        self.assertEqual(saved.revision_id, 41)
        self.assertEqual(saved.annotation_path[-4:], ".xml")
        self.assertEqual(saved.document.boxes[0].label, "saved")
        self.assertEqual(
            loaded.annotation_format,
            AnnotationFormat.PASCAL_VOC,
        )
        self.assertEqual(loaded.document.boxes[0].label, "saved")
        self.assertTrue(loaded.document.verified)

    def test_empty_pascal_document_removes_file_and_cached_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = AnnotationWorkspace(save_dir=directory)
            document = self.document("removed")
            saved = workspace.save(
                document,
                AnnotationFormat.PASCAL_VOC,
            )
            empty_document = AnnotationDocument(
                image_path=self.image_path,
                image_data=self.image,
            )

            removed = workspace.save(
                empty_document,
                AnnotationFormat.PASCAL_VOC,
            )

            self.assertFalse(os.path.exists(saved.annotation_path))
            self.assertTrue(removed.removed)
            self.assertIsNone(removed.document)
            self.assertEqual(workspace.candidate_labels, ())

    def test_save_refuses_to_overwrite_an_external_resource_change(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = AnnotationWorkspace(save_dir=directory)
            saved = workspace.save(
                self.document("first"),
                AnnotationFormat.PASCAL_VOC,
            )
            with open(
                saved.annotation_path,
                "w",
                encoding="utf8",
            ) as annotation:
                annotation.write("<external/>")

            with self.assertRaises(AnnotationStorageConflict):
                workspace.save(
                    self.document("second"),
                    AnnotationFormat.PASCAL_VOC,
                )

            with open(
                saved.annotation_path,
                "r",
                encoding="utf8",
            ) as annotation:
                self.assertEqual(annotation.read(), "<external/>")

    def test_multiple_formats_require_an_explicit_session_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = AnnotationWorkspace(save_dir=directory)
            entry = workspace.entry(self.image_path)
            self.document("voc").save(
                os.path.splitext(
                    entry.path_for(AnnotationFormat.PASCAL_VOC)
                )[0],
                AnnotationFormat.PASCAL_VOC,
            )
            self.document("create").save(
                os.path.splitext(
                    entry.path_for(AnnotationFormat.CREATE_ML)
                )[0],
                AnnotationFormat.CREATE_ML,
            )

            with self.assertRaises(
                AmbiguousAnnotationDocuments
            ) as ambiguity:
                workspace.load_for_image(self.image_path, self.image)
            selected = ambiguity.exception.choices[1]
            workspace.select_active_document(
                self.image_path,
                selected.annotation_path,
            )
            loaded = workspace.load_for_image(
                self.image_path,
                self.image,
            )

        self.assertEqual(
            loaded.annotation_format,
            selected.annotation_format,
        )

    def test_unresolved_multi_format_labels_are_not_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = AnnotationWorkspace(save_dir=directory)
            entry = workspace.entry(self.image_path)
            for annotation_format, label in (
                (AnnotationFormat.PASCAL_VOC, "voc"),
                (AnnotationFormat.CREATE_ML, "create"),
            ):
                self.document(label).save(
                    os.path.splitext(
                        entry.path_for(annotation_format)
                    )[0],
                    annotation_format,
                )

            self.assertEqual(workspace.scan(directory), ())
            choice = workspace.document_choices(self.image_path)[0]
            workspace.select_active_document(
                self.image_path,
                choice.annotation_path,
            )

            self.assertEqual(
                workspace.candidate_labels,
                ("voc",),
            )

    def test_createml_overwrite_uses_retained_collection_not_external_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = AnnotationWorkspace(save_dir=directory)
            saved = workspace.save(
                self.document("first"),
                AnnotationFormat.CREATE_ML,
            )
            with open(saved.annotation_path, "r", encoding="utf8") as source:
                external = json.load(source)
            external.append(
                {"image": "outside.png", "annotations": []}
            )
            with open(saved.annotation_path, "w", encoding="utf8") as target:
                json.dump(external, target)
            with self.assertRaises(AnnotationStorageConflict):
                workspace.save(
                    self.document("second"),
                    AnnotationFormat.CREATE_ML,
                )

            workspace.hold_resource(
                saved.annotation_path, owner=("history", "first")
            )
            workspace.hold_resource(
                saved.annotation_path, owner=("history", "second")
            )
            workspace.release_resource(
                saved.annotation_path, owner=("history", "first")
            )
            workspace.load(
                saved.annotation_path,
                self.image_path,
                self.image,
            )
            self.assertEqual(
                workspace.create_ml_image_names(
                    saved.annotation_path,
                    include_external=False,
                ),
                (os.path.basename(self.image_path),),
            )
            workspace.accept_resource_fingerprints(
                (saved.annotation_path,)
            )
            workspace.save(
                self.document("second"),
                AnnotationFormat.CREATE_ML,
            )
            with open(saved.annotation_path, "r", encoding="utf8") as source:
                overwritten = json.load(source)

        self.assertEqual(
            [record["image"] for record in overwritten],
            [os.path.basename(self.image_path)],
        )

    def test_createml_save_does_not_depend_on_post_commit_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "annotations.json")
            workspace = AnnotationWorkspace(save_dir=directory)

            with patch.object(
                AnnotationDocument,
                "inspect",
                side_effect=RuntimeError("derived index unavailable"),
            ):
                saved = workspace.save(
                    self.document("cat"),
                    AnnotationFormat.CREATE_ML,
                    annotation_path=target,
                )

            self.assertEqual(saved.annotation_path, target)
            with open(target, "r", encoding="utf8") as source:
                records = json.load(source)
            self.assertEqual(
                records[0]["annotations"][0]["label"], "cat"
            )

    def test_existing_createml_collection_rejects_zero_record_match(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "annotations.json")
            with open(target, "w", encoding="utf8") as output:
                json.dump(
                    [{"image": "other.png", "annotations": []}],
                    output,
                )
            workspace = AnnotationWorkspace(save_dir=directory)

            with self.assertRaises(AnnotationDocumentError):
                workspace.save(
                    self.document("cat"),
                    AnnotationFormat.CREATE_ML,
                    annotation_path=target,
                )

            with open(target, "r", encoding="utf8") as source:
                self.assertEqual(
                    json.load(source),
                    [{"image": "other.png", "annotations": []}],
                )

    def test_createml_batch_writes_two_revision_bound_images_once(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = AnnotationWorkspace(save_dir=directory)
            second_image_path = os.path.join(directory, "second.bmp")
            second = replace(
                self.document("dog"),
                image_path=second_image_path,
            )
            target = workspace.entry(self.image_path).path_for(
                AnnotationFormat.CREATE_ML
            )

            saved = workspace.save_createml_batch(
                (
                    (17, self.document("cat")),
                    (23, second),
                ),
                target,
            )
            with open(target, "r", encoding="utf8") as source:
                collection = json.load(source)

        self.assertEqual(
            [item.revision_id for item in saved], [17, 23]
        )
        self.assertEqual(
            {record["image"] for record in collection},
            {
                os.path.basename(self.image_path),
                os.path.basename(second_image_path),
            },
        )
        self.assertEqual(
            workspace.candidate_labels, ("cat", "dog")
        )

    def test_shared_createml_collection_is_a_choice_for_every_record(self):
        with tempfile.TemporaryDirectory() as directory:
            first = os.path.join(directory, "first.png")
            second = os.path.join(directory, "second.png")
            QImage(20, 20, QImage.Format_RGB32).save(first)
            QImage(20, 20, QImage.Format_RGB32).save(second)
            collection = os.path.join(directory, "annotations.json")
            with open(collection, "w", encoding="utf8") as output:
                json.dump(
                    [
                        {"image": "first.png", "annotations": []},
                        {"image": "second.png", "annotations": []},
                    ],
                    output,
                )

            workspace = AnnotationWorkspace(save_dir=directory)
            workspace.scan(directory)

            self.assertEqual(
                [choice.annotation_path for choice in workspace.document_choices(first)],
                [collection],
            )
            self.assertEqual(
                [choice.annotation_path for choice in workspace.document_choices(second)],
                [collection],
            )

    def test_createml_qualified_record_paths_keep_distinct_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            left_dir = os.path.join(directory, "left")
            right_dir = os.path.join(directory, "right")
            os.makedirs(left_dir)
            os.makedirs(right_dir)
            left = os.path.join(left_dir, "same.png")
            right = os.path.join(right_dir, "same.png")
            QImage(20, 20, QImage.Format_RGB32).save(left)
            QImage(20, 20, QImage.Format_RGB32).save(right)
            collection = os.path.join(directory, "annotations.json")
            with open(collection, "w", encoding="utf8") as output:
                json.dump(
                    [
                        {"image": "left/same.png", "annotations": []},
                        {"image": os.path.abspath(right), "annotations": []},
                    ],
                    output,
                )

            workspace = AnnotationWorkspace(save_dir=directory)
            workspace.scan(directory)

            self.assertEqual(
                [choice.annotation_path for choice in workspace.document_choices(left)],
                [collection],
            )
            self.assertEqual(
                [choice.annotation_path for choice in workspace.document_choices(right)],
                [collection],
            )
            loaded = workspace.load(collection, left, QImage(left)).document
            workspace.save(
                loaded,
                AnnotationFormat.CREATE_ML,
                annotation_path=collection,
            )
            with open(collection, "r", encoding="utf8") as source:
                records = json.load(source)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["image"], "left/same.png")

            rebuilt_from_history = replace(
                loaded,
                create_ml_record_name=None,
                verified=True,
            )
            workspace.save(
                rebuilt_from_history,
                AnnotationFormat.CREATE_ML,
                annotation_path=collection,
            )
            with open(collection, "r", encoding="utf8") as source:
                records = json.load(source)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["image"], "left/same.png")
            self.assertEqual(
                workspace.create_ml_image_count(collection), 2
            )

    def test_unsaved_shared_createml_labels_replace_only_one_record(self):
        with tempfile.TemporaryDirectory() as directory:
            first = os.path.join(directory, "first.png")
            collection = os.path.join(directory, "annotations.json")
            with open(collection, "w", encoding="utf8") as output:
                json.dump(
                    [
                        {
                            "image": "first.png",
                            "annotations": [
                                {
                                    "label": "cat",
                                    "coordinates": {
                                        "x": 10,
                                        "y": 10,
                                        "width": 5,
                                        "height": 5,
                                    },
                                }
                            ],
                        },
                        {
                            "image": "second.png",
                            "annotations": [
                                {
                                    "label": "dog",
                                    "coordinates": {
                                        "x": 10,
                                        "y": 10,
                                        "width": 5,
                                        "height": 5,
                                    },
                                }
                            ],
                        },
                    ],
                    output,
                )
            workspace = AnnotationWorkspace(save_dir=directory)
            workspace.scan(directory)
            workspace.record_document(first, collection, ("bird",))

            self.assertEqual(workspace.candidate_labels, ("bird", "dog"))

    def test_scan_preserves_unsaved_candidates_and_yolo_reservations(self):
        with tempfile.TemporaryDirectory() as directory:
            image = os.path.join(directory, "sample.png")
            annotation = os.path.join(directory, "sample.xml")
            workspace = AnnotationWorkspace(save_dir=directory)
            workspace.record_document(image, annotation, ("unsaved",))
            workspace.reserve_yolo_labels(("reserved",))

            workspace.scan(directory)

            self.assertEqual(workspace.candidate_labels, ("unsaved",))
            self.assertEqual(workspace.yolo_vocabulary, ("reserved",))

    def test_shared_createml_ambiguity_is_scoped_to_one_record(self):
        with tempfile.TemporaryDirectory() as directory:
            first = os.path.join(directory, "first.png")
            second = os.path.join(directory, "second.png")
            collection = os.path.join(directory, "annotations.json")
            first_xml = os.path.join(directory, "first.xml")
            first_image = QImage(20, 20, QImage.Format_RGB32)
            first_image.save(first)
            QImage(20, 20, QImage.Format_RGB32).save(second)
            with open(collection, "w", encoding="utf8") as output:
                json.dump(
                    [
                        {
                            "image": "first.png",
                            "annotations": [
                                {"label": "cat", "coordinates": {}}
                            ],
                        },
                        {
                            "image": "second.png",
                            "annotations": [
                                {"label": "dog", "coordinates": {}}
                            ],
                        },
                    ],
                    output,
                )
            replace(
                self.document("bird"),
                image_path=first,
                image_data=first_image,
            ).save(
                os.path.splitext(first_xml)[0],
                AnnotationFormat.PASCAL_VOC,
            )

            workspace = AnnotationWorkspace(save_dir=directory)
            workspace.scan(directory)
            self.assertEqual(workspace.candidate_labels, ("dog",))

            workspace.select_active_document(first, first_xml)
            self.assertEqual(workspace.candidate_labels, ("bird", "dog"))

    def test_strict_createml_validation_rejects_malformed_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "labels.json")
            with open(path, "w", encoding="utf8") as output:
                json.dump(
                    [{"image": "a.png", "annotations": [{}]}],
                    output,
                )

            with self.assertRaises(AnnotationDocumentError):
                AnnotationWorkspace.validate_create_ml_resource(path)


if __name__ == "__main__":
    unittest.main()
