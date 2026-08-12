import os
import unittest

import cv2
import numpy as np

from labelimg.image_tools.domain.colored_frame_removal import (
    ColoredFrameRemover,
    DetectionStrength,
    FrameColor,
    FrameRemovalOptions,
)


REAL_RED_SAMPLE_DIRECTORY = os.environ.get(
    "LABELIMG_RED_FRAME_SAMPLES",
    r"C:\Users\GW-LIYU\Downloads\red_box",
)


def gray_scene(height=240, width=320):
    yy, xx = np.indices((height, width))
    gray = np.clip(
        55 + 0.35 * xx + 0.15 * yy + 7 * np.sin(xx / 11),
        0,
        255,
    ).astype(np.uint8)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def add_frame(image, bounds, color, thickness=7):
    x, y, width, height = bounds
    cv2.rectangle(
        image,
        (x, y),
        (x + width - 1, y + height - 1),
        color,
        thickness,
    )


class ColoredFrameRemovalTest(unittest.TestCase):
    def setUp(self):
        self.options = FrameRemovalOptions(
            colors=frozenset((FrameColor.RED, FrameColor.YELLOW)),
            strength=DetectionStrength.STANDARD,
        )
        self.remover = ColoredFrameRemover(self.options)

    def test_detects_and_repairs_red_and_yellow_rectangular_frames(self):
        clean = gray_scene()
        marked = clean.copy()
        add_frame(marked, (24, 35, 92, 136), (0, 0, 255))
        add_frame(marked, (178, 48, 105, 142), (0, 255, 255))

        analysis = self.remover.analyze(marked)

        self.assertEqual(len(analysis.candidates), 2)
        self.assertEqual(
            {candidate.color for candidate in analysis.candidates},
            {FrameColor.RED, FrameColor.YELLOW},
        )
        result = self.remover.render(marked, analysis)
        self.assertGreater(int(np.count_nonzero(result.mask)), 0)
        repaired_pixels = result.image[result.mask > 0].astype(np.int16)
        expected_pixels = clean[result.mask > 0].astype(np.int16)
        self.assertLessEqual(
            float(np.abs(repaired_pixels - expected_pixels).mean()),
            8.0,
        )

    def test_preserves_solid_red_and_yellow_objects(self):
        image = gray_scene()
        cv2.rectangle(image, (30, 30), (110, 120), (0, 0, 255), -1)
        cv2.circle(image, (235, 115), 42, (0, 255, 255), -1)

        analysis = self.remover.analyze(image)

        self.assertEqual(analysis.candidates, ())
        result = self.remover.render(image, analysis)
        self.assertEqual(int(np.count_nonzero(result.mask)), 0)
        self.assertTrue(np.array_equal(result.image, image))

    def test_can_exclude_one_candidate_without_touching_its_pixels(self):
        image = gray_scene()
        add_frame(image, (24, 35, 92, 136), (0, 0, 255))
        add_frame(image, (178, 48, 105, 142), (0, 255, 255))
        analysis = self.remover.analyze(image)
        red = next(
            candidate
            for candidate in analysis.candidates
            if candidate.color is FrameColor.RED
        )
        yellow = next(
            candidate
            for candidate in analysis.candidates
            if candidate.color is FrameColor.YELLOW
        )

        result = self.remover.render(
            image,
            analysis,
            selected_candidate_ids=(red.candidate_id,),
        )

        self.assertGreater(
            int(np.count_nonzero(result.mask[red.y:red.bottom, red.x:red.right])),
            0,
        )
        self.assertEqual(
            int(np.count_nonzero(result.mask[
                yellow.y:yellow.bottom,
                yellow.x:yellow.right,
            ])),
            0,
        )
        self.assertTrue(np.array_equal(
            result.image[
                yellow.y:yellow.bottom,
                yellow.x:yellow.right,
            ],
            image[
                yellow.y:yellow.bottom,
                yellow.x:yellow.right,
            ],
        ))

    def test_whole_image_grayscale_normalization_is_explicit(self):
        image = gray_scene()
        image[5, 5] = (120, 124, 127)
        add_frame(image, (70, 55, 100, 110), (0, 0, 255))
        analysis = self.remover.analyze(image)

        normal = self.remover.render(image, analysis)
        normalized = ColoredFrameRemover(
            FrameRemovalOptions(
                colors=self.options.colors,
                strength=self.options.strength,
                normalize_near_grayscale=True,
            )
        ).render(image, analysis)

        self.assertFalse(normal.normalized_grayscale)
        self.assertTrue(normalized.normalized_grayscale)
        self.assertGreater(
            int(normal.image[5, 5].max() - normal.image[5, 5].min()),
            0,
        )
        self.assertEqual(
            int(
                (
                    normalized.image.max(axis=2)
                    - normalized.image.min(axis=2)
                ).max()
            ),
            0,
        )

    def test_preserves_alpha_channel(self):
        color = gray_scene(180, 220)
        add_frame(color, (35, 28, 100, 112), (0, 0, 255))
        alpha = np.tile(np.arange(220, dtype=np.uint8), (180, 1))
        image = np.dstack((color, alpha))

        analysis = self.remover.analyze(image)
        result = self.remover.render(image, analysis)

        self.assertTrue(np.array_equal(result.image[:, :, 3], alpha))

    @unittest.skipUnless(
        os.path.isdir(REAL_RED_SAMPLE_DIRECTORY),
        "real red-frame samples are not available",
    )
    def test_detects_a_red_frame_in_every_real_acceptance_sample(self):
        sample_names = sorted(
            name
            for name in os.listdir(REAL_RED_SAMPLE_DIRECTORY)
            if os.path.splitext(name)[1].lower() in (".jpg", ".jpeg")
        )
        self.assertEqual(len(sample_names), 3)
        for sample_name in sample_names:
            with self.subTest(sample=sample_name):
                image = cv2.imdecode(
                    np.fromfile(
                        os.path.join(REAL_RED_SAMPLE_DIRECTORY, sample_name),
                        dtype=np.uint8,
                    ),
                    cv2.IMREAD_COLOR,
                )
                analysis = self.remover.analyze(image)
                self.assertTrue(
                    any(
                        candidate.color is FrameColor.RED
                        for candidate in analysis.candidates
                    ),
                    sample_name,
                )


if __name__ == "__main__":
    unittest.main()
