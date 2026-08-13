import json
import os
import shutil
import tempfile
import unittest
from xml.etree import ElementTree

from PyQt5.QtGui import QColor, QImage

from labelimg.annotations.application.workspace import AnnotationWorkspace
from labelimg.files.application.transaction import FileOperationTransaction
from labelimg.files.application.operations import (
    AnnotationFileService,
    SynchronizedRenamer,
)


class _NoEditing:
    @property
    def image_keys(self):
        return ()

    def has_image(self, _image_key):
        return False

    def dirty_views(self):
        return ()


class _NoScene:
    def forget_image(self, _image_key):
        pass


class _NoPersistence:
    conflicts = {}


class _NoReviewTransaction:
    pass


class FakeTrash:
    def __init__(self, directory):
        self.directory = directory
        self.paths = []

    def __call__(self, path):
        destination = os.path.join(
            self.directory,
            "%03d-%s" % (len(self.paths), os.path.basename(path)),
        )
        shutil.move(path, destination)
        self.paths.append(destination)
        return destination

    def restore(self, identity, destination):
        shutil.move(identity.token, destination)

    def move(self, path):
        return self(path)

    @staticmethod
    def exists(identity):
        return os.path.lexists(identity.token)


def save_image(path, color):
    image = QImage(20, 20, QImage.Format_RGB32)
    image.fill(QColor(color))
    if not image.save(path):
        raise AssertionError("could not save test image")


def write_xml(path, image_path):
    root = ElementTree.Element("annotation")
    ElementTree.SubElement(root, "filename").text = os.path.basename(
        image_path
    )
    ElementTree.SubElement(root, "path").text = image_path
    ElementTree.ElementTree(root).write(
        path,
        encoding="utf-8",
        xml_declaration=True,
    )


class FileOperationsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = self.temporary.name
        self.images = os.path.join(self.root, "images")
        self.annotations = os.path.join(self.root, "annotations")
        self.trash_directory = os.path.join(self.root, "trash")
        os.makedirs(self.images)
        os.makedirs(self.annotations)
        os.makedirs(self.trash_directory)
        self.trash = FakeTrash(self.trash_directory)

    def tearDown(self):
        self.temporary.cleanup()

    def test_associated_resources_include_both_locations_and_shared_files(self):
        first = os.path.join(self.images, "first.png")
        second = os.path.join(self.images, "second.png")
        third = os.path.join(self.images, "third.png")
        for path, color in (
            (first, "white"),
            (second, "black"),
            (third, "red"),
        ):
            save_image(path, color)

        first_xml = os.path.join(self.images, "first.xml")
        write_xml(first_xml, first)
        second_yolo = os.path.join(self.annotations, "second.txt")
        with open(second_yolo, "w", encoding="utf8") as output:
            output.write("0 0.5 0.5 0.2 0.2\n")
        classes = os.path.join(self.annotations, "classes.txt")
        with open(classes, "w", encoding="utf8") as output:
            output.write("object\n")
        shared = os.path.join(self.annotations, "annotations.json")
        with open(shared, "w", encoding="utf8") as output:
            json.dump(
                [
                    {"image": "first.png", "annotations": []},
                    {"image": "second.png", "annotations": []},
                    {"image": "unselected.png", "annotations": []},
                ],
                output,
            )
        unrelated = os.path.join(self.annotations, "unrelated.json")
        with open(unrelated, "w", encoding="utf8") as output:
            json.dump(
                [{"image": "other.png", "annotations": []}],
                output,
            )

        selection = AnnotationFileService(
            save_dir=self.annotations
        ).associated_annotation_resources((first, second, third))

        self.assertEqual(
            selection.resources,
            (first_xml, shared, second_yolo, classes),
        )
        self.assertEqual(selection.images_without_resources, (third,))

    def test_clear_shared_create_ml_preserves_other_record_and_backup(self):
        first = os.path.join(self.images, "first.png")
        second = os.path.join(self.images, "second.png")
        save_image(first, "white")
        save_image(second, "black")
        collection = os.path.join(self.images, "first.json")
        original = [
            {"image": "first.png", "annotations": []},
            {"image": "second.png", "annotations": []},
        ]
        with open(collection, "w", encoding="utf8") as target:
            json.dump(original, target)

        result = AnnotationFileService(
            trash=self.trash
        ).clear_annotations([first])

        self.assertEqual(result.failed_images, [])
        with open(collection, "r", encoding="utf8") as source:
            self.assertEqual(
                json.load(source),
                [{"image": "second.png", "annotations": []}],
            )
        self.assertEqual(len(self.trash.paths), 1)
        with open(self.trash.paths[0], "r", encoding="utf8") as source:
            self.assertEqual(json.load(source), original)

    def test_clear_two_records_in_one_collection_has_one_recoverable_resource(self):
        first = os.path.join(self.images, "first.png")
        second = os.path.join(self.images, "second.png")
        save_image(first, "white")
        save_image(second, "black")
        collection = os.path.join(self.images, "annotations.json")
        original = [
            {"image": "first.png", "annotations": []},
            {"image": "second.png", "annotations": []},
        ]
        with open(collection, "w", encoding="utf8") as output:
            json.dump(original, output)

        transaction = FileOperationTransaction(
            AnnotationWorkspace(),
            _NoEditing(),
            _NoScene(),
            _NoPersistence(),
            _NoReviewTransaction(),
            self.trash,
        )
        outcome = transaction.execute("clear", (first, second))
        result = outcome.file_result

        self.assertEqual(result.failed_images, [])
        self.assertEqual(len(result.trashed_resources), 1)
        transaction.recover(outcome.recovery_entry.entry_id)
        with open(collection, "r", encoding="utf8") as source:
            self.assertEqual(json.load(source), original)

    def test_delete_clears_annotations_from_both_locations(self):
        image_path = os.path.join(self.images, "sample.png")
        save_image(image_path, "white")
        expected = [image_path]
        for directory in (self.images, self.annotations):
            for extension in (".xml", ".txt"):
                path = os.path.join(directory, "sample" + extension)
                with open(path, "w", encoding="utf8") as target:
                    target.write("annotation")
                expected.append(path)
            json_path = os.path.join(directory, "sample.json")
            with open(json_path, "w", encoding="utf8") as target:
                json.dump(
                    [{"image": "sample.png", "annotations": []}],
                    target,
                )
            expected.append(json_path)

        result = AnnotationFileService(
            save_dir=self.annotations,
            trash=self.trash,
        ).delete_images([image_path])

        self.assertEqual(result.failed_images, [])
        self.assertEqual(len(self.trash.paths), len(expected))
        for path in expected:
            self.assertFalse(os.path.exists(path))

    def test_synchronized_rename_updates_all_annotation_formats(self):
        source = os.path.join(self.images, "cat.png")
        target = os.path.join(self.images, "Cat-renamed.png")
        save_image(source, "white")
        xml_path = os.path.join(self.images, "cat.xml")
        write_xml(xml_path, source)
        text_path = os.path.join(self.annotations, "cat.txt")
        with open(text_path, "w", encoding="utf8") as target_file:
            target_file.write("0 0.5 0.5 1 1")
        json_path = os.path.join(self.annotations, "cat.json")
        with open(json_path, "w", encoding="utf8") as target_file:
            json.dump(
                [{"image": "cat.png", "annotations": []}],
                target_file,
            )

        SynchronizedRenamer(
            save_dir=self.annotations
        ).rename({source: target})

        self.assertTrue(os.path.isfile(target))
        self.assertFalse(os.path.exists(source))
        renamed_xml = os.path.join(self.images, "Cat-renamed.xml")
        root = ElementTree.parse(renamed_xml).getroot()
        self.assertEqual(root.findtext("filename"), "Cat-renamed.png")
        self.assertEqual(
            root.findtext("path"),
            os.path.abspath(target),
        )
        self.assertTrue(os.path.isfile(
            os.path.join(self.annotations, "Cat-renamed.txt")
        ))
        renamed_json = os.path.join(
            self.annotations,
            "Cat-renamed.json",
        )
        with open(renamed_json, "r", encoding="utf8") as source_file:
            self.assertEqual(
                json.load(source_file)[0]["image"],
                "Cat-renamed.png",
            )

    def test_batch_rename_can_swap_names(self):
        first = os.path.join(self.images, "a.png")
        second = os.path.join(self.images, "b.png")
        with open(first, "wb") as target:
            target.write(b"first")
        with open(second, "wb") as target:
            target.write(b"second")

        SynchronizedRenamer().rename(
            {first: second, second: first}
        )

        with open(first, "rb") as source:
            self.assertEqual(source.read(), b"second")
        with open(second, "rb") as source:
            self.assertEqual(source.read(), b"first")

    def test_rename_splits_matching_record_from_shared_collection(self):
        source = os.path.join(self.images, "a.png")
        target = os.path.join(self.images, "c.png")
        save_image(source, "white")
        collection = os.path.join(self.images, "a.json")
        with open(collection, "w", encoding="utf8") as target_file:
            json.dump(
                [
                    {"image": "a.png", "annotations": []},
                    {"image": "b.png", "annotations": []},
                ],
                target_file,
            )

        SynchronizedRenamer().rename({source: target})

        with open(collection, "r", encoding="utf8") as source_file:
            self.assertEqual(
                json.load(source_file),
                [{"image": "b.png", "annotations": []}],
            )
        with open(
            os.path.join(self.images, "c.json"),
            "r",
            encoding="utf8",
        ) as source_file:
            self.assertEqual(
                json.load(source_file),
                [{"image": "c.png", "annotations": []}],
            )

    def test_failed_logical_target_rolls_back_already_trashed_resources(self):
        image = os.path.join(self.images, "sample.png")
        save_image(image, "red")
        xml = os.path.join(self.annotations, "sample.xml")
        yolo = os.path.join(self.annotations, "sample.txt")
        write_xml(xml, image)
        with open(yolo, "w", encoding="utf8") as output:
            output.write("0 0.5 0.5 0.2 0.2\n")

        class FailSecondTrash(FakeTrash):
            def __call__(self, path):
                if len(self.paths) == 1:
                    raise RuntimeError("second trash failure")
                return super().__call__(path)

        result = AnnotationFileService(
            save_dir=self.annotations,
            trash=FailSecondTrash(self.trash_directory),
        ).clear_annotations((image,))

        self.assertEqual(result.succeeded_images, [])
        self.assertEqual(result.trashed_resources, [])
        self.assertTrue(os.path.isfile(xml))
        self.assertTrue(os.path.isfile(yolo))

    def test_failed_image_delete_restores_its_trashed_annotations(self):
        image = os.path.join(self.images, "sample.png")
        save_image(image, "red")
        xml = os.path.join(self.annotations, "sample.xml")
        write_xml(xml, image)

        class FailImageTrash(FakeTrash):
            def __call__(self, path):
                if path == image:
                    raise RuntimeError("image trash failure")
                return super().__call__(path)

        result = AnnotationFileService(
            save_dir=self.annotations,
            trash=FailImageTrash(self.trash_directory),
        ).delete_images((image,))

        self.assertEqual(result.succeeded_images, [])
        self.assertEqual(result.trashed_resources, [])
        self.assertTrue(os.path.isfile(image))
        self.assertTrue(os.path.isfile(xml))

    def test_partial_rollback_retains_only_still_trashed_resources(self):
        image = os.path.join(self.images, "sample.png")
        save_image(image, "red")
        xml = os.path.join(self.annotations, "sample.xml")
        yolo = os.path.join(self.annotations, "sample.txt")
        invalid_json = os.path.join(self.annotations, "sample.json")
        write_xml(xml, image)
        with open(yolo, "w", encoding="utf8") as output:
            output.write("0 0.5 0.5 0.2 0.2\n")
        with open(invalid_json, "w", encoding="utf8") as output:
            json.dump({"not": "createml"}, output)

        class FailYoloRestore(FakeTrash):
            def restore(self, identity, destination):
                if identity.original_path == yolo:
                    raise RuntimeError("yolo restore failure")
                super().restore(identity, destination)

        trash = FailYoloRestore(self.trash_directory)
        result = AnnotationFileService(
            save_dir=self.annotations,
            trash=trash,
        ).clear_annotations((image,))

        self.assertEqual(len(result.trashed_resources), 1)
        self.assertEqual(
            result.trashed_resources[0].original_path, yolo
        )
        self.assertTrue(os.path.isfile(xml))
        self.assertFalse(os.path.exists(yolo))


if __name__ == "__main__":
    unittest.main()
