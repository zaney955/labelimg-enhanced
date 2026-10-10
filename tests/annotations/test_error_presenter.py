"""Localized annotation diagnostics survive error wrappers and HTML rendering."""

import unittest
from labelimg.annotations.domain.model import (
    AnnotationDocumentError,
    YoloClassMappingError,
)
from labelimg.annotations.ui.errors import annotation_error_text, annotation_error_html
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language


class AnnotationErrorPresenterTest(unittest.TestCase):
    def tearDown(self):
        set_language(ENGLISH)

    def test_wrapped_mapping_error_uses_selected_language(self):
        inner = YoloClassMappingError(
            "missing",
            "sample.txt",
            line_number=1,
            checked_paths=("classes.txt", "data.yaml"),
        )
        outer = AnnotationDocumentError("sample.txt: " + str(inner))
        outer.__cause__ = inner
        for language, phrase in [
            (SIMPLIFIED_CHINESE, "缺少 YOLO 类别映射"),
            (ENGLISH, "Missing YOLO class mapping"),
        ]:
            set_language(language)
            self.assertIn(phrase, annotation_error_text(outer))
            self.assertIn("classes.txt", annotation_error_text(outer))

    def test_html_escapes_paths_and_preserves_line_breaks(self):
        set_language(ENGLISH)
        error = YoloClassMappingError(
            "out_of_range",
            "<image>&.txt",
            line_number=3,
            class_index=3,
            class_count=2,
            class_list_path="a&b/classes.txt",
        )
        text = annotation_error_html(error)
        self.assertIn("&lt;image&gt;&amp;.txt", text)
        self.assertIn("a&amp;b/classes.txt", text)
        self.assertIn("<br>", text)

    def test_unrelated_errors_keep_their_details(self):
        error = ValueError("ordinary failure")
        self.assertEqual(annotation_error_text(error), "ordinary failure")


if __name__ == "__main__":
    unittest.main()
