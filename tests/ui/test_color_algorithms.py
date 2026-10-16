"""Behavioral checks for stable name colors and session maximin allocation."""

import json
import os
import subprocess
import sys
import unittest

from labelimg.annotations.ui.color_algorithms import (
    SessionColorAllocator,
    candidate_colors,
    distance_squared,
    fixed_label_rgb,
    oklch_to_rgb,
    rgb_to_oklab,
)


class ColorAlgorithmsTest(unittest.TestCase):
    def test_conversion_matches_reference_srgb_primaries(self):
        for rgb, expected in (
            ((0, 0, 0), (0, 0, 0)),
            ((255, 255, 255), (1, 0, 0)),
            ((255, 0, 0), (0.627955, 0.224863, 0.125846)),
            ((0, 255, 0), (0.866440, -0.233888, 0.179498)),
            ((0, 0, 255), (0.452014, -0.032457, -0.311528)),
        ):
            with self.subTest(rgb=rgb):
                for actual, reference in zip(rgb_to_oklab(rgb), expected):
                    self.assertAlmostEqual(actual, reference, places=5)

    def test_fixed_v1_colors_are_locked_for_full_names_and_unicode(self):
        for label, expected in (
            ("P_LS_LM2", (0, 214, 145)),
            ("P_LS_LM3", (255, 153, 193)),
            ("P_LSBM", (210, 161, 0)),
            ("cat", (130, 152, 255)),
            ("Cat", (203, 122, 224)),
        ):
            self.assertEqual(fixed_label_rgb(label), expected)
        labels = ["类别", "類別", "cat", "Cat", "cat ", "P_LS_LM2", "P_LS_LM3"]
        self.assertEqual(len({fixed_label_rgb(label) for label in labels}), len(labels))

    def test_fixed_colors_are_independent_of_process_hash_seed_and_request_order(self):
        labels = ["P_LS_LM2", "P_LS_LM3", "P_LSBM", "类别"]
        expected = {label: list(fixed_label_rgb(label)) for label in labels}
        script = (
            "import json; from labelimg.annotations.ui.color_algorithms import fixed_label_rgb; "
            f"print(json.dumps({{label: fixed_label_rgb(label) for label in {labels!r}}}))"
        )
        for seed in ("1", "42"):
            output = subprocess.check_output(
                [sys.executable, "-c", script],
                env=os.environ | {"PYTHONHASHSEED": seed}, text=True,
            )
            self.assertEqual(json.loads(output), expected)
        for label in reversed(labels):
            self.assertEqual(list(fixed_label_rgb(label)), expected[label])

    def test_fixed_colors_and_gamut_reduction_keep_controlled_lightness(self):
        for label in [f"P_LSBM{i}" for i in range(300)] + ["类别", "P_LSBM"]:
            rgb = fixed_label_rgb(label)
            lightness, a, b = rgb_to_oklab(rgb)
            self.assertTrue(all(0 <= channel <= 255 for channel in rgb))
            self.assertGreaterEqual(lightness, 0.698)
            self.assertLessEqual(lightness, 0.822)
            self.assertGreater((a * a + b * b) ** 0.5, 0.07)
        for hue in range(0, 360, 10):
            lightness = rgb_to_oklab(oklch_to_rgb(0.75, 0.4, hue))[0]
            self.assertAlmostEqual(lightness, 0.75, delta=0.002)

    def assert_maximin(self, selected, references):
        def score(rgb):
            lab = rgb_to_oklab(rgb)
            return min(distance_squared(lab, rgb_to_oklab(ref)) for ref in references)

        best = max(score(rgb) for rgb, _lab in candidate_colors())
        self.assertAlmostEqual(score(selected), best, places=12)

    def test_session_allocates_farthest_colors_and_never_moves_existing_labels(self):
        allocator = SessionColorAllocator()
        assigned = {}
        for label in [f"class-{i}" for i in range(15)]:
            rgb = allocator.color(label, {})
            if assigned:
                self.assert_maximin(rgb, assigned.values())
            self.assertNotIn(rgb, assigned.values())
            assigned[label] = rgb
            for known, expected in assigned.items():
                self.assertEqual(allocator.color(known, {}), expected)

    def test_custom_colors_affect_new_allocations_without_moving_existing_ones(self):
        allocator = SessionColorAllocator()
        first = allocator.color("first", {})
        custom = (255, 0, 0)
        allocator.invalidate()
        second = allocator.color("second", {"first": custom})
        self.assert_maximin(second, [custom])
        self.assertEqual(allocator.color("first", {}), first)
        allocator.invalidate()
        third = allocator.color("third", {})
        self.assert_maximin(third, [first, second])

    def test_session_references_and_first_seen_order_can_change_assignments(self):
        first, second = SessionColorAllocator(), SessionColorAllocator()
        alone = first.color("P_LSBM", {})
        second.color("P_LS_LM2", {})
        self.assertNotEqual(second.color("P_LSBM", {}), alone)
        self.assertTrue(second.clear())
        self.assertEqual(second.color("P_LSBM", {}), alone)


if __name__ == "__main__":
    unittest.main()
