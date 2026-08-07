import os
import json
import io
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image

from labelimg.annotation_history import AnnotationBoxState
from labelimg.image_tools.crop import (
    CropRegion,
    ImageCropProcessor,
    crop_pixels,
    transform_annotation_boxes,
)
from labelimg.image_tools.crop_annotation import prepare_crop_annotations
from labelimg.annotation_history import AnnotationSnapshot
from labelimg.annotation_storage import fingerprint_path
from labelimg.image_tools.image_file_codec import ImageFileCodec


class ImageCropTest(unittest.TestCase):
    def test_crop_pixels_preserves_channel_layout_and_uses_integer_region(self):
        region = CropRegion(2, 1, 3, 2)
        for pixels in (
            np.arange(6 * 8, dtype=np.uint8).reshape(6, 8),
            np.arange(6 * 8 * 3, dtype=np.uint8).reshape(6, 8, 3),
            np.arange(6 * 8 * 4, dtype=np.uint8).reshape(6, 8, 4),
        ):
            with self.subTest(shape=pixels.shape):
                cropped = crop_pixels(pixels, region)
                np.testing.assert_array_equal(
                    cropped,
                    pixels[1:3, 2:5],
                )
                self.assertTrue(cropped.flags.c_contiguous)

    def test_crop_region_rejects_out_of_bounds_and_no_op(self):
        with self.assertRaises(ValueError):
            CropRegion(-1, 0, 2, 2).validate((8, 6))
        with self.assertRaises(ValueError):
            CropRegion(0, 0, 0, 2).validate((8, 6))
        self.assertTrue(CropRegion(0, 0, 8, 6).is_full_image((8, 6)))
        self.assertFalse(CropRegion(1, 0, 7, 6).is_full_image((8, 6)))

    def test_annotation_boxes_translate_clip_and_remove(self):
        boxes = (
            self.box(1, ((3, 2), (5, 2), (5, 4), (3, 4))),
            self.box(2, ((0, 1), (3, 1), (3, 5), (0, 5))),
            self.box(3, ((0, 0), (1, 0), (1, 1), (0, 1))),
        )

        result = transform_annotation_boxes(
            boxes,
            CropRegion(2, 1, 4, 4),
        )

        self.assertEqual(result.clipped_count, 1)
        self.assertEqual(result.removed_count, 1)
        self.assertEqual(result.retained_ids, (1, 2))
        self.assertEqual(
            result.boxes[0].points,
            ((1, 1), (3, 1), (3, 3), (1, 3)),
        )
        self.assertEqual(
            result.boxes[1].points,
            ((0, 0), (1, 0), (1, 4), (0, 4)),
        )
        self.assertEqual(result.boxes[1].label, "box-2")

    def test_any_positive_intersection_is_retained_without_threshold(self):
        result = transform_annotation_boxes(
            (self.box(1, ((0, 0), (3, 0), (3, 3), (0, 3))),),
            CropRegion(2, 2, 2, 2),
        )

        self.assertEqual(result.removed_count, 0)
        self.assertEqual(result.clipped_count, 1)
        self.assertEqual(
            result.boxes[0].points,
            ((0, 0), (1, 0), (1, 1), (0, 1)),
        )

    def test_codec_allows_explicit_resized_output_and_updates_exif_dimensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = os.path.join(temporary, "source.jpg")
            exif = Image.Exif()
            exif[40962] = 8
            exif[40963] = 6
            Image.new("RGB", (8, 6), (120, 130, 140)).save(
                path,
                exif=exif,
            )
            codec = ImageFileCodec()
            loaded = codec.load(path)
            cropped = crop_pixels(loaded.pixels, CropRegion(2, 1, 3, 2))

            content = codec.encode(loaded, cropped, output_size=(3, 2))

            result_path = os.path.join(temporary, "result.jpg")
            with open(result_path, "wb") as target:
                target.write(content)
            with Image.open(result_path) as result:
                self.assertEqual(result.size, (3, 2))
                self.assertEqual(result.getexif()[40962], 3)
                self.assertEqual(result.getexif()[40963], 2)

    def test_processor_prepares_resized_image_and_annotation_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = os.path.join(temporary, "source.png")
            Image.new("RGB", (8, 6), (120, 130, 140)).save(path)
            snapshot = AnnotationSnapshot(
                image_key=path,
                image_size=(8, 6),
                boxes=(
                    self.box(
                        7,
                        ((3, 2), (6, 2), (6, 5), (3, 5)),
                    ),
                ),
                verified=True,
            )

            prepared = ImageCropProcessor().prepare(
                path,
                CropRegion(2, 1, 4, 4),
                snapshot,
            )

            self.assertEqual(prepared.snapshot.image_size, (4, 4))
            self.assertEqual(prepared.snapshot.boxes[0].session_id, 7)
            self.assertEqual(prepared.clipped_count, 0)
            self.assertEqual(
                prepared.image_replacement.expected_fingerprint,
                fingerprint_path(path),
            )
            with Image.open(
                __import__("io").BytesIO(
                    prepared.image_replacement.content
                )
            ) as result:
                self.assertEqual(result.size, (4, 4))

    def test_create_ml_preparation_changes_only_the_current_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            image_path = os.path.join(temporary, "first.png")
            Image.new("RGB", (8, 6), "white").save(image_path)
            target = os.path.join(temporary, "annotations.json")
            other = {
                "image": "second.png",
                "annotations": [{
                    "label": "other",
                    "coordinates": {
                        "x": 2,
                        "y": 2,
                        "width": 2,
                        "height": 2,
                    },
                }],
            }
            with open(target, "w", encoding="utf8") as output:
                json.dump([
                    {"image": "first.png", "annotations": []},
                    other,
                ], output)
            snapshot = AnnotationSnapshot(
                image_key=image_path,
                image_size=(4, 4),
                boxes=(self.box(1, ((0, 0), (2, 0), (2, 2), (0, 2))),),
            )

            with open(image_path, "rb") as source:
                image_content = source.read()
            prepared = prepare_crop_annotations(
                snapshot,
                image_content,
                target,
                create_ml_record_name="first.png",
            )

            self.assertEqual(len(prepared.replacements), 1)
            payload = json.loads(
                prepared.replacements[0].content.decode("utf8")
            )
            self.assertEqual(payload[1], other)
            self.assertEqual(payload[0]["image"], "first.png")
            self.assertEqual(len(payload[0]["annotations"]), 1)

    def test_yolo_preparation_allows_an_empty_annotation_resource(self):
        with tempfile.TemporaryDirectory() as temporary:
            image_path = os.path.join(temporary, "first.png")
            Image.new("RGB", (8, 6), "white").save(image_path)
            target = os.path.join(temporary, "first.txt")
            with open(target, "w", encoding="utf8") as output:
                output.write("0 0.5 0.5 0.5 0.5\n")
            with open(
                os.path.join(temporary, "classes.txt"),
                "w",
                encoding="utf8",
            ) as output:
                output.write("box\n")
            buffer = io.BytesIO()
            Image.new("RGB", (4, 4), "white").save(
                buffer, format="PNG"
            )
            snapshot = AnnotationSnapshot(
                image_key=image_path,
                image_size=(4, 4),
                boxes=(),
            )

            prepared = prepare_crop_annotations(
                snapshot,
                buffer.getvalue(),
                target,
                class_names=("box",),
            )

            annotation = next(
                item for item in prepared.replacements
                if item.path == target
            )
            self.assertIsInstance(annotation.content, bytes)
            self.assertNotIn(b"0 0.5", annotation.content)

    @staticmethod
    def box(session_id, points):
        return AnnotationBoxState(
            session_id=session_id,
            label="box-%d" % session_id,
            points=tuple(points),
            line_rgba=(1, 2, 3, 255),
            fill_rgba=(4, 5, 6, 80),
            difficult=bool(session_id % 2),
        )


if __name__ == "__main__":
    unittest.main()
