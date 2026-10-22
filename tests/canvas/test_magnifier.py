"""Loupe chrome follows the theme while sampling and protected placement hold."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication

from labelimg.canvas.magnifier import magnifier_rect, paint_magnifier
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.ui.theme import (
    COLORS,
    LIGHT_THEME,
    available_themes,
    register_theme,
    set_theme,
)


class MagnifierThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.alternate = LIGHT_THEME.with_overrides(
            "test-loupe",
            name_en="Test Loupe",
            name_zh="测试放大镜",
            surface="#F0FAF8",
            accent="#337A70",
            muted="#3D6660",
        )
        if cls.alternate.identifier not in {t.identifier for t in available_themes()}:
            register_theme(cls.alternate)

    def tearDown(self):
        set_theme(LIGHT_THEME.identifier)
        set_language(ENGLISH)

    def render(
        self, *, density=1, center=QPointF(100, 80), protected=None, language=ENGLISH
    ):
        set_language(language)
        source = QImage(200, 160, QImage.Format_RGB32)
        source.fill(QColor("#426855"))
        output = QImage(round(500 * density), round(350 * density), QImage.Format_RGB32)
        output.setDevicePixelRatio(density)
        output.fill(QColor("#A0A0A0"))
        viewport = QRectF(0, 0, 500, 350)
        position = QPointF(100, 80)
        painter = QPainter(output)
        paint_magnifier(
            painter,
            QPixmap.fromImage(source),
            QSize(200, 160),
            center,
            position,
            viewport,
            1,
            protected_rect=protected,
        )
        painter.end()
        return output, magnifier_rect(position, viewport, protected)

    def test_light_footer_and_image_detail_are_independent(self):
        image, rect = self.render()
        self.assertEqual(
            image.pixelColor(round(rect.left() + 10), round(rect.bottom() - 5)).name(),
            COLORS["surface"].lower(),
        )
        self.assertEqual(
            image.pixelColor(round(rect.left() + 12), round(rect.top() + 12)),
            QColor("#426855"),
        )
        # The unchanged reverse-screen crosshair is drawn over the image center.
        self.assertNotEqual(
            image.pixelColor(round(rect.center().x()), round(rect.top() + 25)),
            QColor("#426855"),
        )

    def test_live_theme_changes_only_chrome_not_sampled_pixels(self):
        first, rect = self.render()
        set_theme(self.alternate.identifier)
        second, _ = self.render()
        self.assertNotEqual(
            first.pixelColor(round(rect.left() + 10), round(rect.bottom() - 5)),
            second.pixelColor(round(rect.left() + 10), round(rect.bottom() - 5)),
        )
        self.assertEqual(
            second.pixelColor(round(rect.left() + 10), round(rect.bottom() - 5)).name(),
            COLORS["surface"].lower(),
        )
        self.assertEqual(
            first.pixelColor(round(rect.left() + 12), round(rect.top() + 12)),
            second.pixelColor(round(rect.left() + 12), round(rect.top() + 12)),
        )

    def test_image_edge_uses_neutral_well_and_keeps_valid_detail(self):
        image, rect = self.render(center=QPointF(0, 0))
        self.assertEqual(
            image.pixelColor(round(rect.left() + 10), round(rect.top() + 10)).name(),
            COLORS["preview_background"].lower(),
        )
        self.assertEqual(
            image.pixelColor(round(rect.right() - 10), round(rect.top() + 75)),
            QColor("#426855"),
        )

    def test_bilingual_scaled_render_stays_outside_pending_box(self):
        protected = QRectF(50, 40, 150, 120)
        for language in (ENGLISH, SIMPLIFIED_CHINESE):
            for density in (1, 1.25, 1.5):
                image, rect = self.render(
                    density=density, protected=protected, language=language
                )
                self.assertFalse(rect.intersects(protected.adjusted(-8, -8, 8, 8)))
                self.assertTrue(QRectF(0, 0, 500, 350).contains(rect))
                self.assertEqual(
                    image.pixelColor(
                        round((rect.left() + 10) * density),
                        round((rect.bottom() - 5) * density),
                    ).name(),
                    COLORS["surface"].lower(),
                )

    def test_no_loupe_when_pending_box_leaves_no_safe_room(self):
        image, rect = self.render(protected=QRectF(0, 0, 500, 350))
        self.assertTrue(rect.isEmpty())
        self.assertEqual(image.pixelColor(200, 200), QColor("#A0A0A0"))


if __name__ == "__main__":
    unittest.main()
