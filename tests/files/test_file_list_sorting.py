import os
import tempfile
import unittest
from functools import cmp_to_key

from labelimg.workbench.main_window import MainWindow, portable_logical_compare


class FileListSortingTest(unittest.TestCase):
    def test_images_keep_relative_directories_as_natural_batches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            nested_dir = os.path.join(temp_dir, "zzz")
            os.makedirs(nested_dir)
            paths = [
                os.path.join(temp_dir, "0dc52y1wpm.jpg"),
                os.path.join(temp_dir, "01z2revfcj.jpg"),
                os.path.join(temp_dir, "042jl90w74.jpg"),
                os.path.join(temp_dir, "07oa6axaiz.jpg"),
                os.path.join(temp_dir, "10aozc9brc.jpg"),
                os.path.join(temp_dir, "a9n2wdrngy.jpg"),
                os.path.join(temp_dir, "a70zu3nrb8.jpg"),
                os.path.join(nested_dir, "00nested.jpg"),
            ]
            for path in paths:
                with open(path, "wb"):
                    pass

            actual_paths = [
                os.path.relpath(path, temp_dir)
                for path in MainWindow.scan_all_images(None, temp_dir)
            ]

            self.assertEqual(
                actual_paths,
                [
                    "0dc52y1wpm.jpg",
                    "01z2revfcj.jpg",
                    "07oa6axaiz.jpg",
                    "10aozc9brc.jpg",
                    "042jl90w74.jpg",
                    "a9n2wdrngy.jpg",
                    "a70zu3nrb8.jpg",
                    os.path.join("zzz", "00nested.jpg"),
                ],
            )

    def test_portable_sort_matches_windows_explorer_name_order(self):
        names = [
            "a70zu3nrb8.jpg",
            "042jl90w74.jpg",
            "0dc52y1wpm.jpg",
            "10aozc9brc.jpg",
            "00nested.jpg",
            "a9n2wdrngy.jpg",
            "07oa6axaiz.jpg",
            "01z2revfcj.jpg",
        ]

        self.assertEqual(
            sorted(names, key=cmp_to_key(portable_logical_compare)),
            [
                "00nested.jpg",
                "0dc52y1wpm.jpg",
                "01z2revfcj.jpg",
                "07oa6axaiz.jpg",
                "10aozc9brc.jpg",
                "042jl90w74.jpg",
                "a9n2wdrngy.jpg",
                "a70zu3nrb8.jpg",
            ],
        )


if __name__ == "__main__":
    unittest.main()
