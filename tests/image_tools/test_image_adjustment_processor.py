import io
import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from labelimg.image_tools.application.adjustment import (
    ImageAdjustmentOptions,
    ImageAdjustmentProcessor,
    apply_adjustments,
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

    def test_brightness_preserves_grayscale_jpeg_channel_mode(self):
        pixels = np.array(
            [[10, 80], [160, 240]],
            dtype=np.uint8,
        )
        path = self._save("grayscale.jpg", pixels, "L")

        result = ImageAdjustmentProcessor().prepare(
            path,
            ImageAdjustmentOptions(brightness=10),
        )

        self.assertIsNotNone(result.replacement)
        with Image.open(path) as original:
            self.assertEqual(original.mode, "L")
        with Image.open(io.BytesIO(result.replacement.content)) as adjusted:
            self.assertEqual(adjusted.mode, "L")

    def test_lookup_adjustment_matches_reference_pipeline(self):
        pixels = np.arange(256, dtype=np.uint8).reshape(16, 16)
        options = ImageAdjustmentOptions(
            brightness=-17,
            contrast=1.37,
            gamma=0.8,
        )
        linear = np.clip(
            pixels.astype(np.float32) * options.contrast
            + options.brightness * 2.55,
            0,
            255,
        ).round().astype(np.uint8)
        gamma = np.array([
            round(((value / 255.0) ** (1.0 / options.gamma)) * 255)
            for value in range(256)
        ], dtype=np.uint8)

        result = apply_adjustments(pixels, options)

        np.testing.assert_array_equal(result, gamma[linear])

    def test_commit_preparation_can_release_full_resolution_arrays(self):
        path = self._save(
            "memory.png",
            np.full((12, 16, 3), 80, dtype=np.uint8),
            "RGB",
        )

        result = ImageAdjustmentProcessor().prepare(
            path,
            ImageAdjustmentOptions(brightness=10),
            retain_pixels=False,
        )

        self.assertIsNotNone(result.replacement)
        self.assertIsNone(result.original_pixels)
        self.assertIsNone(result.result_pixels)


if __name__ == "__main__":
    unittest.main()
