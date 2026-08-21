import json
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from labelimg.image_tools.domain.quality import (
    ImageQualityCache,
    ImageQualityPolicy,
    ImageQualityScanner,
)


class ImageQualityScannerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.scanner = ImageQualityScanner()

    def tearDown(self):
        self.temporary.cleanup()

    def save(self, name, pixels):
        path = os.path.join(self.temporary.name, name)
        Image.fromarray(np.asarray(pixels, dtype=np.uint8)).save(path)
        return path

    def test_standard_scan_explains_low_resolution_dark_and_blur(self):
        path = self.save("dark.png", np.full((32, 48, 3), 10))
        result = self.scanner.scan(path, ImageQualityPolicy.standard())

        self.assertEqual(result.size, (48, 32))
        self.assertEqual(
            {finding.code for finding in result.findings},
            {"low_resolution", "blur", "dark"},
        )
        for finding in result.findings:
            self.assertTrue(finding.explanation)
            self.assertIsNotNone(finding.metric)
            self.assertIsNotNone(finding.threshold)

    def test_corrupt_image_is_reported_instead_of_raising(self):
        path = os.path.join(self.temporary.name, "broken.png")
        with open(path, "wb") as stream:
            stream.write(b"not an image")

        result = self.scanner.scan(path, ImageQualityPolicy.standard())

        self.assertEqual([item.code for item in result.findings], ["unreadable"])
        self.assertIsNotNone(result.error)

    def test_workspace_scan_marks_an_aspect_outlier(self):
        first = self.save("a.png", np.full((100, 100, 3), 120))
        second = self.save("b.png", np.full((100, 110, 3), 120))
        outlier = self.save("wide.png", np.full((40, 200, 3), 120))
        policy = ImageQualityPolicy.standard().with_overrides(
            min_width=1,
            min_height=1,
            blur_variance=-1,
        )

        results = self.scanner.scan_many((first, second, outlier), policy)

        self.assertNotIn("aspect_anomaly", {
            item.code for item in results[first].findings
        })
        self.assertIn("aspect_anomaly", {
            item.code for item in results[outlier].findings
        })

    def test_large_image_metrics_use_bounded_pixels_and_keep_source_size(self):
        path = self.save("large.png", np.full((300, 400, 3), 120))

        with patch.object(self.scanner, "ANALYSIS_MAX_PIXELS", 10_000):
            result = self.scanner.scan(path)

        self.assertEqual(result.size, (400, 300))


class ImageQualityCacheTest(unittest.TestCase):
    def test_cache_key_includes_file_fingerprint_and_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            image_path = os.path.join(temporary, "sample.png")
            Image.new("RGB", (16, 16), (90, 90, 90)).save(image_path)
            cache = ImageQualityCache(os.path.join(temporary, "quality.json"))
            scanner = ImageQualityScanner()
            policy = ImageQualityPolicy.standard()
            result = scanner.scan(image_path, policy)
            cache.put(result)

            self.assertEqual(cache.get(image_path, policy), result)
            changed = policy.with_overrides(dark_mean=5)
            self.assertIsNone(cache.get(image_path, changed))
            Image.new("RGB", (16, 16), (91, 91, 91)).save(image_path)
            self.assertIsNone(cache.get(image_path, policy))

            cache.clear()
            self.assertFalse(os.path.exists(cache.path))


if __name__ == "__main__":
    unittest.main()
