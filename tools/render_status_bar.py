"""Render and exercise the real unified footer with disposable workbench data."""

import argparse
import json
import os
from pathlib import Path
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=("en", "zh_CN"), default="zh_CN")
    parser.add_argument("--scale", type=float, choices=(1, 1.25, 1.5), default=1)
    parser.add_argument("--mode", choices=("light", "dark"), default="light")
    parser.add_argument("--ui-scale", type=int, default=100, choices=(75, 100, 125, 150, 200))
    parser.add_argument("--native", action="store_true", help="Exercise Windows windows and native Qt popup behavior")
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(exist_ok=True)
    os.environ["QT_QPA_PLATFORM"] = "windows" if args.native else "offscreen"
    os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    os.environ["LABELIMG_CONFIG_DIR"] = str(root / "config")

    from PyQt5.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt, QTimer
    from PyQt5.QtGui import QColor, QFont, QFontDatabase, QImage, QMouseEvent, QScreen, QStatusTipEvent
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication, QMessageBox, QStatusBar, QStyle, QStyleOptionSlider
    from labelimg.annotations.domain.model import AnnotationFormat
    from labelimg.annotations.infrastructure.document import AnnotationBox, AnnotationDocument
    from labelimg.localization.runtime import tr
    from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench
    from labelimg.ui.theme import COLORS
    from labelimg.ui.theme_palettes import contrast_ratio
    from labelimg.ui.metrics import dp

    app = QApplication.instance() or QApplication([])
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 9))
    screen = QRect(0, 0, round(1920 / args.scale), round(1080 / args.scale))
    screen_patch = patch.object(QScreen, "availableGeometry", lambda self: screen)
    screen_patch.start()
    classes = root / "classes.txt"
    classes.write_text("", encoding="utf-8")
    image_path = root / "fixture.png"
    image = QImage(1200, 800, QImage.Format_RGB32)
    image.fill(QColor("#C2CBD4"))
    image.save(str(image_path))
    AnnotationDocument(str(image_path), image, boxes=(
        AnnotationBox("C_BPU", ((160, 140), (480, 140), (480, 320), (160, 320))),
    )).save(str(image_path.with_suffix("")), AnnotationFormat.PASCAL_VOC)
    window = create_workbench(WorkbenchLaunchOptions(class_file=str(classes), save_dir=""))
    window.auto_saving.setChecked(False)
    window.change_language(args.language)
    window.appearance.apply_preferences(args.mode, "plum")
    window.ui_scale.set_percent(args.ui_scale, persist=False)
    window.resize(1600, 720)
    window.show()
    bar = window.statusBar()
    manifest = []

    def pump():
        for _ in range(5):
            app.processEvents()

    def rect_in(widget, parent):
        point = widget.mapTo(parent, QPoint())
        return QRect(point, widget.size())

    def capture(name, *, full=False):
        pump()
        errors = []
        if len(window.findChildren(QStatusBar)) != 1 or bar.width() != window.width():
            errors.append("footer does not span window exactly once")
        regions = [bar.readouts, bar.feedback, bar.view_controls]
        for widget in regions:
            if not bar.surface.rect().contains(widget.geometry()):
                errors.append("footer region outside surface")
        for left, right in zip(regions, regions[1:]):
            if left.geometry().intersects(right.geometry()):
                errors.append("overlapping footer regions")
        for label in (bar.coordinates, bar.dimensions):
            if (label.fontMetrics().horizontalAdvance(label.text()) > label.width()
                    or label.fontMetrics().height() > label.height()):
                errors.append("clipped coordinate or dimension")
        for control in (bar.magnifier_button, bar.zoom.minus, bar.zoom.slider,
                        bar.zoom.plus, bar.zoom.value_button, bar.details_button,
                        getattr(window, "directory_load_button", None)):
            if control is not None and control.isVisible():
                if not bar.rect().contains(rect_in(control, bar)):
                    errors.append("interactive control outside footer")
        footer_pixels = bar.grab()
        pixels = footer_pixels.toImage()
        dpr = footer_pixels.devicePixelRatioF()
        background = pixels.pixelColor(round(2 * dpr), pixels.height() // 2).name()
        gap_x = bar.feedback.mapTo(bar, QPoint()).x() - dp(4)
        gap_color = pixels.pixelColor(round(gap_x * dpr), pixels.height() // 2).name()
        if background.lower() != COLORS["panel_header"].lower() or gap_color.lower() != background.lower():
            errors.append("footer retains an outdated theme background")
        text_contrast = min(
            contrast_ratio(label.palette().color(label.foregroundRole()).name(), background)
            for label in (bar.coordinates, bar.dimensions, bar.message_label)
        )
        if text_contrast < 4.5:
            errors.append("footer copy contrast below 4.5:1")
        if not footer_pixels.save(str(root / (name + "-footer.png"))):
            errors.append("PNG save failed")
        if full:
            window.grab().save(str(root / (name + "-window.png")))
        manifest.append(dict(
            name=name, errors=errors, window=[window.width(), window.height()],
            height=bar.height(), dpr=bar.devicePixelRatioF(), stacked=bar.stacked,
            background=background, text_contrast=text_contrast,
            message=bar.currentMessage(), slider_width=bar.zoom.slider.width(),
            regions=[[w.x(), w.y(), w.width(), w.height()] for w in regions],
        ))

    capture("01-empty-wide")
    window.resize(1024, 720)
    assert window.load_file(str(image_path))
    bar.clearMessage()
    pump()
    shape = window.canvas.shapes[0]
    point = window.canvas.image_to_widget(QPointF(240, 200))
    QApplication.sendEvent(window.canvas, QMouseEvent(
        QEvent.MouseMove, point, Qt.NoButton, Qt.NoButton, Qt.NoModifier,
    ))
    assert bar.currentMessage() == tr("canvas.moveShape", label=shape.label)
    capture("02-hover-narrow", full=True)
    bar.showMessage("temporary operation result", 5000)
    window.create_shape()
    assert bar.currentMessage() == tr("canvas.hintDrawStart")
    assert bar.dimensions.text() == ""
    capture("02a-draw-ready", full=True)
    corner = window.canvas.image_to_widget(QPointF(520, 340)).toPoint()
    QTest.mousePress(window.canvas, Qt.LeftButton, pos=corner)
    assert bar.currentMessage() == tr("canvas.hintDrawFinish")
    capture("02b-drawing")
    QTest.keyClick(window.canvas, Qt.Key_Escape)
    QTest.mouseRelease(window.canvas, Qt.LeftButton, pos=corner)
    assert bar.currentMessage() != tr("canvas.hintDrawFinish")
    capture("02c-canceled")
    window.set_pan_mode()
    assert bar.currentMessage() == tr("canvas.hintPan")
    capture("02d-pan")
    window.set_edit_mode()
    hover_position = window.canvas.image_to_widget(QPointF(240, 220))
    QApplication.sendEvent(window.canvas, QMouseEvent(
        QEvent.MouseMove, hover_position, Qt.NoButton, Qt.NoButton, Qt.NoModifier,
    ))
    assert window.enter_crop_mode()
    assert bar.currentMessage() == tr("canvas.hintCrop")
    assert not bar.dimensions.text()
    capture("02e-crop")
    window.cancel_crop()
    QApplication.sendEvent(window.canvas, QEvent(QEvent.Leave))
    assert shape.label not in bar.currentMessage()
    capture("02f-left-canvas")
    window._ensure_directory_loading()
    window.directory_load_button.show()
    window._directory_feedback("directoryLoading.indexing", count=12345)
    pump()
    origin = bar.zoom.slider.mapToGlobal(QPoint())
    height = bar.height()
    capture("03-loading")
    QTest.mouseClick(window.directory_load_button, Qt.LeftButton)
    assert bar.currentMessage() == tr("directoryLoading.stopped")
    capture("04-stopped")
    window._directory_feedback("directoryLoading.failed", error="Permission denied: " + "long/path/" * 60)
    QApplication.sendEvent(window, QStatusTipEvent("lower priority hint"))
    assert bar.currentMessage().startswith(tr("directoryLoading.failed", error=""))
    with patch("labelimg.workbench.canvas_status.information") as details:
        QTest.mouseClick(bar.details_button, Qt.LeftButton)
        assert details.call_args.args[2] == bar.currentMessage()
    if args.native:
        details_seen = []

        def close_details():
            for dialog in app.topLevelWidgets():
                if isinstance(dialog, QMessageBox) and dialog.isVisible():
                    dialog.grab().save(str(root / "05-failed-details.png"))
                    details_seen.append(dialog.text())
                    dialog.accept()

        QTimer.singleShot(100, close_details)
        QTest.mouseClick(bar.details_button, Qt.LeftButton)
        assert details_seen == [bar.currentMessage()]
    capture("05-failed", full=True)
    assert bar.zoom.slider.mapToGlobal(QPoint()) == origin
    assert bar.height() == height
    window._complete_directory_feedback()
    bar.clearMessage()
    # Exercise the actual zoom buttons, slider drag, magnifier, and preset menu.
    before = window.zoom_widget.value()
    QTest.mouseClick(bar.zoom.plus, Qt.LeftButton)
    assert bar.zoom.value() > before
    slider = bar.zoom.slider
    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    handle = slider.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderHandle, slider).center()
    before = bar.zoom.value()
    QTest.mousePress(slider, Qt.LeftButton, pos=handle)
    bar.showMessage("temporary result " * 80)
    pump()
    assert slider.mapToGlobal(QPoint()) == origin
    destination = handle + QPoint(8, 0)
    QApplication.sendEvent(slider, QMouseEvent(
        QEvent.MouseMove, QPointF(destination), Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
    ))
    QTest.mouseRelease(slider, Qt.LeftButton, pos=destination)
    assert bar.zoom.value() >= before
    checked = bar.magnifier_button.isChecked()
    QTest.mouseClick(bar.magnifier_button, Qt.LeftButton)
    assert bar.magnifier_button.isChecked() != checked
    bar.zoom.menu.popup(bar.zoom.value_button.mapToGlobal(QPoint()))
    pump()
    assert bar.zoom.menu.isVisible() and len(bar.zoom.menu.actions()) == 3
    bar.zoom.menu.close()
    bar.zoom.menu.actions()[0].trigger()
    assert bar.zoom.value() == 100
    bar.zoom.slider.setFocus()
    capture("06-focused-controls")
    # Large values must fit without changing the original-image readout rules.
    bar.set_image_size(QSize(200000, 100000))
    bar.coordinates.setText("X: 199999  Y: 99999")
    bar.dimensions.setText("W: 200000  H: 100000")
    capture("07-large-values")
    summary = dict(language=args.language, mode=args.mode, system_scale=args.scale,
                   application_scale=args.ui_scale,
                   platform=app.platformName(),
                   states=manifest, interaction_checks="passed")
    (root / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(output=str(root), states=len(manifest),
                          errors=sum(len(s["errors"]) for s in manifest))))
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    screen_patch.stop()
    return int(any(s["errors"] for s in manifest))


if __name__ == "__main__":
    raise SystemExit(main())
