import io
import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from labelimg.annotations.domain.history import AnnotationBoxState, AnnotationSnapshot
from labelimg.image_tools.application.geometry_transform import (
    GeometryOperation,
    ImageGeometryProcessor,
)


class ImageGeometryTransformTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temporary.name, "geometry.png")
        pixels = np.zeros((4, 6, 3), dtype=np.uint8)
        pixels[0, 0] = (255, 0, 0)
        pixels[3, 5] = (0, 255, 0)
        Image.fromarray(pixels, "RGB").save(self.path)
        self.snapshot = AnnotationSnapshot(
            image_key=self.path,
            image_size=(6, 4),
            boxes=(
                AnnotationBoxState(
                    session_id=7,
                    label="box",
                    points=((1, 1), (5, 1), (5, 3), (1, 3)),
                ),
            ),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_clockwise_rotation_transforms_pixels_and_annotation_space(self):
        result = ImageGeometryProcessor().prepare(
            self.path,
            GeometryOperation.ROTATE_CLOCKWISE,
            self.snapshot,
        )

        self.assertEqual(result.snapshot.image_size, (4, 6))
        self.assertEqual(
            result.snapshot.boxes[0].points,
            ((1, 1), (3, 1), (3, 5), (1, 5)),
        )
        self.assertEqual(result.snapshot.boxes[0].session_id, 7)
        with Image.open(io.BytesIO(result.image_replacement.content)) as image:
            self.assertEqual(image.size, (4, 6))
            rotated = np.asarray(image)
        np.testing.assert_array_equal(rotated[0, 3], (255, 0, 0))
        np.testing.assert_array_equal(rotated[5, 0], (0, 255, 0))

    def test_flip_and_resize_use_literal_expected_coordinates(self):
        processor = ImageGeometryProcessor()

        flipped = processor.prepare(
            self.path,
            GeometryOperation.FLIP_HORIZONTAL,
            self.snapshot,
        )
        self.assertEqual(
            flipped.snapshot.boxes[0].points,
            ((1, 1), (5, 1), (5, 3), (1, 3)),
        )

        resized = processor.prepare(
            self.path,
            GeometryOperation.RESIZE,
            self.snapshot,
            output_size=(3, 2),
        )
        self.assertEqual(resized.snapshot.image_size, (3, 2))
        self.assertEqual(
            resized.snapshot.boxes[0].points,
            ((0.5, 0.5), (2.5, 0.5), (2.5, 1.5), (0.5, 1.5)),
        )
        with Image.open(io.BytesIO(resized.image_replacement.content)) as image:
            self.assertEqual(image.size, (3, 2))

    def test_resize_rejects_aspect_ratio_distortion(self):
        with self.assertRaisesRegex(ValueError, "aspect ratio"):
            ImageGeometryProcessor().prepare(
                self.path,
                GeometryOperation.RESIZE,
                self.snapshot,
                output_size=(4, 4),
            )

    def test_resize_accepts_nearest_pixel_rounding_for_odd_dimensions(self):
        pixels = np.zeros((2, 3, 3), dtype=np.uint8)
        path = os.path.join(self.temporary.name, "odd.png")
        Image.fromarray(pixels, "RGB").save(path)
        snapshot = AnnotationSnapshot(
            image_key=path,
            image_size=(3, 2),
            boxes=(),
        )

        result = ImageGeometryProcessor().prepare(
            path,
            GeometryOperation.RESIZE,
            snapshot,
            output_size=(2, 1),
        )

        self.assertEqual(result.snapshot.image_size, (2, 1))


if __name__ == "__main__":
    unittest.main()
