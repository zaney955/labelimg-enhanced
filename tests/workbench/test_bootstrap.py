import os
import unittest

from labelimg.workbench.bootstrap import (
    WorkbenchLaunchOptions,
    create_workbench,
    parse_launch_options,
)


class WorkbenchBootstrapTest(unittest.TestCase):
    def test_cli_is_parsed_before_the_concrete_window_is_constructed(self):
        options = parse_launch_options((
            "labelImg",
            os.path.join("images", "day1"),
            os.path.join("classes", "labels.txt"),
            os.path.join("annotations", "day1"),
        ))
        calls = []
        window = object()

        def compose(candidate, *args):
            calls.append((candidate, args))

        result = create_workbench(
            options,
            window_factory=lambda: window,
            composer=compose,
        )

        self.assertIs(result, window)
        self.assertEqual(
            calls,
            [(window, (
                os.path.normpath(os.path.join("images", "day1")),
                os.path.normpath(os.path.join("classes", "labels.txt")),
                os.path.normpath(os.path.join("annotations", "day1")),
            ))],
        )

    def test_composition_rejects_untyped_launch_requests(self):
        with self.assertRaises(TypeError):
            create_workbench({"image_dir": "images"})

        self.assertEqual(
            WorkbenchLaunchOptions().image_dir,
            None,
        )


if __name__ == "__main__":
    unittest.main()
