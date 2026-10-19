"""Native control glyphs and delegate artwork share vector rendering."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QRect, QRectF
from PyQt5.QtGui import QIcon, QImage, QPainter
from PyQt5.QtWidgets import (
    QAbstractSpinBox, QApplication, QStyle, QStyleOption,
    QStyleOptionComboBox, QStyleOptionSpinBox,
)

from labelimg.ui.icons import icon, install_icon_style, paint_icon


class IconStyleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        install_icon_style()

    def render_glyph(self, *, dpr=1, enabled=True, primitive=None):
        image = QImage(28 * dpr, 28 * dpr, QImage.Format_ARGB32)
        image.setDevicePixelRatio(dpr)
        image.fill(0)
        painter = QPainter(image)
        if primitive is None:
            paint_icon(painter, QRectF(0, 0, 28, 28), "filter", enabled=enabled)
        else:
            option = QStyleOption()
            option.rect = QRect(6, 6, 16, 16)
            option.state = QStyle.State_Enabled if enabled else QStyle.State_None
            self.app.style().drawPrimitive(primitive, option, painter)
        painter.end()
        return image

    def test_high_dpi_and_disabled_glyphs_remain_visible_and_centered(self):
        for dpr in (1, 2, 3):
            normal = self.render_glyph(dpr=dpr)
            disabled = self.render_glyph(dpr=dpr, enabled=False)
            self.assertNotEqual(normal, disabled)
            for image in (normal, disabled):
                ink = [(x, y) for y in range(image.height()) for x in range(image.width())
                       if image.pixelColor(x, y).alpha()]
                self.assertTrue(ink)
                self.assertGreater(min(x for x, y in ink), 0)
                self.assertLess(max(x for x, y in ink), image.width() - 1)
                self.assertGreater(min(y for x, y in ink), 0)
                self.assertLess(max(y for x, y in ink), image.height() - 1)

    def test_native_arrow_primitives_use_shared_chevrons(self):
        for primitive, name in ((QStyle.PE_IndicatorArrowDown, "chevron-down"),
                                (QStyle.PE_IndicatorSpinUp, "chevron-up")):
            expected = QImage(28, 28, QImage.Format_ARGB32)
            expected.fill(0)
            painter = QPainter(expected)
            paint_icon(painter, QRect(6, 6, 16, 16), name, size=16)
            painter.end()
            self.assertEqual(self.render_glyph(primitive=primitive), expected)

    def test_qt_clear_and_message_icons_use_shared_artwork(self):
        for standard, name in ((QStyle.SP_LineEditClearButton, "clear"),
                               (QStyle.SP_MessageBoxWarning, "status-warning"),
                               (QStyle.SP_DialogResetButton, "reset")):
            actual = self.app.style().standardIcon(standard)
            for mode in (QIcon.Normal, QIcon.Disabled):
                self.assertEqual(actual.pixmap(24, 24, mode).toImage(),
                                 icon(name).pixmap(24, 24, mode).toImage())

    def test_installing_for_multiple_windows_preserves_the_style(self):
        style = self.app.style()
        install_icon_style()
        self.assertIs(self.app.style(), style)

    def test_themed_controls_draw_shared_arrows_and_respect_spin_limits(self):
        style = self.app.style()
        image = QImage(140, 32, QImage.Format_ARGB32)
        painter = QPainter(image)
        combo = QStyleOptionComboBox()
        combo.rect = QRect(0, 0, 140, 32)
        combo.state = QStyle.State_Enabled
        combo.subControls = QStyle.SC_All
        with patch.object(style, "drawPrimitive", wraps=style.drawPrimitive) as draw:
            style.drawComplexControl(QStyle.CC_ComboBox, combo, painter)
            calls = [call for call in draw.call_args_list if call.args[0] == QStyle.PE_IndicatorArrowDown]
            self.assertEqual(len(calls), 1)
        spin = QStyleOptionSpinBox()
        spin.rect = combo.rect
        spin.state = QStyle.State_Enabled
        spin.subControls = QStyle.SC_All
        spin.stepEnabled = QAbstractSpinBox.StepUpEnabled
        with patch.object(style, "drawPrimitive", wraps=style.drawPrimitive) as draw:
            style.drawComplexControl(QStyle.CC_SpinBox, spin, painter)
            up = next(call.args[1] for call in draw.call_args_list if call.args[0] == QStyle.PE_IndicatorSpinUp)
            down = next(call.args[1] for call in draw.call_args_list if call.args[0] == QStyle.PE_IndicatorSpinDown)
            self.assertTrue(up.state & QStyle.State_Enabled)
            self.assertFalse(down.state & QStyle.State_Enabled)
        painter.end()


if __name__ == "__main__":
    unittest.main()
