import os
import tempfile
import unittest

from labelimg.app import MainWindow


class FileListSortingTest(unittest.TestCase):
    def test_images_match_windows_explorer_name_order(self):
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

            actual_names = [
                os.path.basename(path)
                for path in MainWindow.scan_all_images(None, temp_dir)
            ]

            self.assertEqual(
                actual_names,
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
