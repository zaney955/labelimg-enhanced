import json
import os
import tempfile
import unittest

from labelimg.annotations.infrastructure.formats.create_ml_collection import (
    CreateMLAnnotationCollection,
    CreateMLCollectionFormatError,
    CreateMLRecordAmbiguous,
)


def annotation(label):
    return {
        "label": label,
        "coordinates": {
            "x": 10,
            "y": 10,
            "width": 4,
            "height": 6,
        },
    }


class CreateMLAnnotationCollectionTest(unittest.TestCase):
    def test_resolve_preserves_qualified_record_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            collection = os.path.join(directory, "annotations.json")
            left = os.path.join(directory, "left", "same.png")
            right = os.path.join(directory, "right", "same.png")
            payload = [
                {"image": "left/same.png", "annotations": []},
                {"image": os.path.abspath(right), "annotations": []},
            ]

            model = CreateMLAnnotationCollection.read(
                collection, content=json.dumps(payload)
            )

            self.assertEqual(model.resolve(left).reference, "left/same.png")
            self.assertEqual(model.resolve(right).reference, right)

    def test_legacy_basename_ambiguity_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            collection = os.path.join(directory, "annotations.json")
            payload = [
                {"image": "same.png", "annotations": []},
                {"image": "SAME.PNG", "annotations": []},
            ]
            model = CreateMLAnnotationCollection.read(
                collection, content=json.dumps(payload)
            )

            with self.assertRaises(CreateMLRecordAmbiguous):
                model.resolve(os.path.join(directory, "same.png"))

    def test_strict_validation_rejects_malformed_annotations(self):
        with tempfile.TemporaryDirectory() as directory:
            collection = os.path.join(directory, "annotations.json")

            with self.assertRaises(CreateMLCollectionFormatError):
                CreateMLAnnotationCollection.read(
                    collection,
                    content=json.dumps(
                        [{"image": "sample.png", "annotations": [{}]}]
                    ),
                    strict=True,
                )

    def test_upsert_preserves_other_records_and_original_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "annotations.json")
            model = CreateMLAnnotationCollection.read(
                path,
                content=json.dumps(
                    [
                        {
                            "image": "nested/sample.png",
                            "annotations": [annotation("old")],
                        },
                        {
                            "image": "other.png",
                            "annotations": [annotation("other")],
                        },
                    ]
                ),
            )

            updated = model.upsert_annotation_record(
                "nested/sample.png",
                (
                    {
                        "label": "new",
                        "points": ((8, 7), (12, 7), (12, 13), (8, 13)),
                    },
                ),
                questioned=True,
            )
            payload = json.loads(updated.to_bytes())

            self.assertEqual(payload[0]["image"], "nested/sample.png")
            self.assertEqual(payload[0]["annotations"][0]["label"], "new")
            self.assertTrue(payload[0]["questioned"])
            self.assertEqual(payload[1]["annotations"][0]["label"], "other")

    def test_remove_image_preserves_unrelated_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "annotations.json")
            model = CreateMLAnnotationCollection.read(
                path,
                content=json.dumps(
                    [
                        {"image": "first.png", "annotations": []},
                        {"image": "second.png", "annotations": []},
                    ]
                ),
            )

            retained = model.remove_image(
                os.path.join(directory, "first.png"), required=True
            )

            self.assertEqual(retained.references, ("second.png",))

    def test_rename_plan_splits_exact_multi_record_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "first.png")
            target = os.path.join(directory, "renamed.png")
            collection_path = os.path.join(directory, "first.json")
            model = CreateMLAnnotationCollection.read(
                collection_path,
                content=json.dumps(
                    [
                        {"image": "first.png", "annotations": []},
                        {"image": "other.png", "annotations": []},
                    ]
                ),
            )

            plan = model.plan_rename(
                {source: target}, exact_owner=source
            )

            self.assertTrue(plan.changed)
            self.assertEqual(plan.source.references, ("other.png",))
            self.assertEqual(len(plan.targets), 1)
            target_path, contribution = plan.targets[0]
            self.assertEqual(
                target_path,
                os.path.join(directory, "renamed.json"),
            )
            self.assertEqual(contribution.references, ("renamed.png",))

    def test_rename_plan_keeps_qualified_same_basenames_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            left = os.path.join(directory, "left", "same.png")
            right = os.path.join(directory, "right", "same.png")
            left_target = os.path.join(directory, "left", "left-new.png")
            right_target = os.path.join(directory, "right", "right-new.png")
            path = os.path.join(directory, "annotations.json")
            model = CreateMLAnnotationCollection.read(
                path,
                content=json.dumps(
                    [
                        {"image": "left/same.png", "annotations": []},
                        {"image": os.path.abspath(right), "annotations": []},
                    ]
                ),
            )

            plan = model.plan_rename(
                {left: left_target, right: right_target}
            )

            self.assertEqual(
                plan.source.references,
                (
                    "left/left-new.png",
                    os.path.abspath(right_target),
                ),
            )

    def test_merge_rejects_duplicate_record_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "annotations.json")
            first = CreateMLAnnotationCollection.read(
                path,
                content=json.dumps(
                    [{"image": "sample.png", "annotations": []}]
                ),
            )
            duplicate = CreateMLAnnotationCollection.read(
                path,
                content=json.dumps(
                    [{"image": "SAMPLE.PNG", "annotations": []}]
                ),
            )

            with self.assertRaises(CreateMLCollectionFormatError):
                first.merge(duplicate)


if __name__ == "__main__":
    unittest.main()
