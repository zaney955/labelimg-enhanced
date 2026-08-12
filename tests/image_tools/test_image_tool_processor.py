import os
import tempfile
import unittest

import cv2
import numpy as np
from PIL import Image

from labelimg.image_tools.domain.colored_frame_removal import (
    FrameColor,
    FrameRemovalOptions,
)
from labelimg.image_tools.application.colored_frame_processor import ImageToolProcessor


class ImageToolProcessorTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.processor = ImageToolProcessor()

    def tearDown(self):
        self.temporary.cleanup()

    def path(self, name):
        return os.path.join(self.temporary.name, name)

    @staticmethod
    def marked_image(red=True, yellow=True):
        image = np.full((180, 240, 3), 120, dtype=np.uint8)
        if red:
            cv2.rectangle(image, (20, 25), (95, 145), (0, 0, 255), 7)
        if yellow:
            cv2.rectangle(image, (140, 30), (220, 150), (0, 255, 255), 7)
        return image

    def save_bgr(self, name, image):
        path = self.path(name)
        Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)).save(path)
        return path

    @staticmethod
    def read(path):
        with open(path, "rb") as source:
            return source.read()

    def test_prepares_a_valid_replacement_without_writing_the_source(self):
        path = self.save_bgr("marked.png", self.marked_image())
        original_bytes = self.read(path)

        prepared = self.processor.prepare(path, FrameRemovalOptions())

        self.assertEqual(len(prepared.candidates), 2)
        self.assertEqual(
            {candidate.color for candidate in prepared.candidates},
            {FrameColor.RED, FrameColor.YELLOW},
        )
        self.assertIsNotNone(prepared.replacement)
        self.assertGreater(int(np.count_nonzero(prepared.mask)), 0)
        self.assertEqual(self.read(path), original_bytes)
        self.assertEqual(prepared.replacement.path, path)

    def test_no_frame_result_has_no_replacement_and_keeps_exact_bytes(self):
        path = self.save_bgr(
            "plain.jpg",
            np.full((100, 120, 3), 100, dtype=np.uint8),
        )
        original_bytes = self.read(path)

        prepared = self.processor.prepare(path, FrameRemovalOptions())

        self.assertEqual(prepared.candidates, ())
        self.assertIsNone(prepared.replacement)
        self.assertEqual(self.read(path), original_bytes)

    def test_reselecting_candidates_reuses_analysis_and_can_exclude_all(self):
        path = self.save_bgr("marked.bmp", self.marked_image())
        prepared = self.processor.prepare(path, FrameRemovalOptions())
        red = next(
            candidate
            for candidate in prepared.candidates
            if candidate.color is FrameColor.RED
        )

        red_only = self.processor.select_candidates(
            prepared,
            (red.candidate_id,),
        )
        excluded = self.processor.select_candidates(prepared, ())

        self.assertEqual(red_only.selected_candidate_ids, (red.candidate_id,))
        self.assertIsNotNone(red_only.replacement)
        self.assertIsNone(excluded.replacement)
        self.assertEqual(int(np.count_nonzero(excluded.mask)), 0)
        self.assertTrue(np.array_equal(
            excluded.original_pixels,
            excluded.result_pixels,
        ))


if __name__ == "__main__":
    unittest.main()
