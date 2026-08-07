import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from labelimg.image_tools.adjustment import (
    ImageAdjustmentOptions,
    ImageAdjustmentProcessor,
)


class ImageAdjustmentProcessorTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temporary.cleanup()

    def _save(self, name, pixels, mode):
        path = os.path.join(self.temporary.name, name)
        Image.fromarray(pixels, mode).save(path)
        return path

    def test_safe_defaults_are_an_exact_no_op(self):
        pixels = np.array(
            [[[10, 20, 30], [100, 120, 140]]],
            dtype=np.uint8,
        )
        path = self._save("default.png", pixels, "RGB")

        result = ImageAdjustmentProcessor().prepare(path)

        np.testing.assert_array_equal(result.result_pixels, result.original_pixels)
        self.assertIsNone(result.replacement)

    def test_brightness_contrast_gamma_and_grayscale_compose(self):
        pixels = np.array([[[10, 80, 200]]], dtype=np.uint8)
        path = self._save("compose.png", pixels, "RGB")
        options = ImageAdjustmentOptions(
            brightness=20,
            contrast=1.25,
            gamma=0.8,
            grayscale=True,
        )

        result = ImageAdjustmentProcessor().prepare(path, options)

        self.assertIsNotNone(result.replacement)
        channels = result.result_pixels[0, 0]
        self.assertEqual(int(channels[0]), int(channels[1]))
        self.assertEqual(int(channels[1]), int(channels[2]))

    def test_rgba_grayscale_preserves_alpha_bytes(self):
        pixels = np.array(
            [[[10, 80, 200, 17], [200, 30, 40, 231]]],
            dtype=np.uint8,
        )
        path = self._save("alpha.png", pixels, "RGBA")

        result = ImageAdjustmentProcessor().prepare(
            path,
            ImageAdjustmentOptions(grayscale=True),
        )

        np.testing.assert_array_equal(
            result.result_pixels[..., 3],
            np.array([[17, 231]], dtype=np.uint8),
        )


if __name__ == "__main__":
    unittest.main()
