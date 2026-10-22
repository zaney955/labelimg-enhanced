"""Render real label/file selection states with disposable annotation fixtures."""

import argparse
import json
import os
from pathlib import Path
from unittest.mock import patch
from html import escape

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--language", choices=("zh_CN", "en"), default="zh_CN")
parser.add_argument("--scale", type=float, default=1.0)
parser.add_argument(
    "--baseline",
    action="store_true",
    help="Capture the previous package without asserting the new row treatment",
)
args = parser.parse_args()
if args.scale <= 0:
    parser.error("--scale must be positive")
root = args.output.resolve()
root.mkdir(parents=True, exist_ok=True)
(root / "config").mkdir(exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = str(args.scale)
os.environ["LABELIMG_CONFIG_DIR"] = str(root / "config")
from PyQt5.QtCore import QEvent, QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QImage, QScreen
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from labelimg.annotations.domain.model import AnnotationFormat
from labelimg.annotations.infrastructure.document import (
    AnnotationBox,
    AnnotationDocument,
)
from labelimg.platform.settings import Settings
from labelimg.platform.settings_keys import SETTING_AUTO_CHECK_UPDATES
from labelimg.ui.theme import COLORS
from labelimg.ui.theme_palettes import available_accents, contrast_ratio
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench

app = QApplication([])
font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
if font.is_file():
    identifier = QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont(QFontDatabase.applicationFontFamilies(identifier)[0], 9))
settings = Settings()
settings[SETTING_AUTO_CHECK_UPDATES] = False
settings.save()
classes = root / "classes.txt"
classes.write_text("", encoding="utf-8")
images = root / "images"
images.mkdir(exist_ok=True)
fixtures = [
    AnnotationBox("裂纹", ((30, 30), (120, 30), (120, 90), (30, 90))),
    AnnotationBox("裂纹", ((150, 40), (230, 40), (230, 110), (150, 110))),
    AnnotationBox("缺损", ((90, 140), (160, 140), (160, 200), (90, 200))),
    AnnotationBox("划伤", ((250, 130), (300, 130), (300, 210), (250, 210))),
]
for i in range(4):
    path = images / f"sample_{i+1:02}.png"
    image = QImage(360, 240, QImage.Format_RGB32)
    image.fill(QColor("#8B98A4"))
    image.save(str(path))
    AnnotationDocument(str(path), image, boxes=tuple(fixtures)).save(
        str(path.with_suffix("")), AnnotationFormat.PASCAL_VOC
    )
manifest = []
virtual = QRect(0, 0, round(1920 / args.scale), round(1080 / args.scale))
with patch.object(QScreen, "availableGeometry", lambda self: virtual):
    w = create_workbench(WorkbenchLaunchOptions(class_file=str(classes)))
    w.auto_saving.setChecked(False)
    w.change_language(args.language)
    w.resize(min(1440, virtual.width()), min(900, virtual.height()))
    w.show()
    w.import_dir_images(str(images))
    app.processEvents()
    w.resizeDocks([w.dock, w.file_dock], [360, 360], Qt.Horizontal)
    w.resizeDocks([w.dock, w.file_dock], [350, 280], Qt.Vertical)
    app.processEvents()
    groups = {
        label: w.label_list.group_shapes(label) for label in w.label_list.group_labels()
    }
    full = groups["裂纹"] + groups["缺损"]
    partial = (groups["裂纹"][0], groups["缺损"][0])
    for row in (0, 2):
        w.file_list_widget.item(row).setSelected(True)
    before_colors = tuple(shape.line_color.rgba() for shape in w.canvas.shapes)
    try:
        for mode in (("light",) if args.baseline else ("light", "dark")):
            accents = [
                a
                for a in available_accents()
                if not args.baseline or a.identifier == "plum"
            ]
            for accent in accents:
                w.appearance.apply_preferences(mode, accent.identifier)
                for state in ("full", "partial", "focus-out", "hover"):
                    selected = full if state == "full" else partial
                    w.canvas.set_selected_shapes(selected, active_shape=None)
                    w.label_list.setFocus()
                    QTest.mouseMove(w.edit_button)
                    if state in ("focus-out", "hover"):
                        w.edit_button.setFocus()
                    if state == "hover":
                        QTest.mouseMove(
                            w.label_list.viewport(),
                            w.label_list.group_body_rect("裂纹").center(),
                        )
                    app.processEvents()
                    QTest.qWait(15)
                    assert set(w.label_list.selected_shapes()) == set(selected)
                    assert (
                        tuple(shape.line_color.rgba() for shape in w.canvas.shapes)
                        == before_colors
                    )
                    assert len(w.selected_file_paths()) == 2
                    pixels = w.label_list.viewport().grab()
                    dpr = pixels.devicePixelRatioF()
                    if not args.baseline:
                        im = pixels.toImage()
                        for label in ("裂纹", "缺损"):
                            row = w.label_list.row_rect_for_label(label)
                            assert (
                                w.label_list.viewport().rect().contains(row)
                            ), "selected row is clipped"
                            point = row.topLeft() + QPoint(18, 5)
                            assert im.pixelColor(
                                round(point.x() * dpr), round(point.y() * dpr)
                            ) == QColor(COLORS["selection_background"])
                        assert (
                            contrast_ratio(
                                COLORS["selection_foreground"],
                                COLORS["selection_background"],
                            )
                            >= 4.5
                        )
                    name = f"{mode}-{accent.identifier}-{state}"
                    file = root / (name + ".png")
                    w.dock.grab().save(str(file))
                    manifest.append(
                        {
                            "name": name,
                            "file": str(file),
                            "language": args.language,
                            "scale": args.scale,
                            "mode": mode,
                            "accent": accent.identifier,
                            "state": state,
                            "geometry_checks": (
                                "baseline" if args.baseline else "passed"
                            ),
                            "device_pixel_ratio": dpr,
                        }
                    )
                    if accent.identifier == "plum" and state == "partial":
                        hero = root / f"{mode}-workbench.png"
                        w.grab().save(str(hero))
        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        cards = "".join(
            f'<article><a href="{Path(m["file"]).name}"><img loading="lazy" src="{Path(m["file"]).name}"></a><p>{escape(m["name"])}</p></article>'
            for m in manifest
        )
        (root / "index.html").write_text(
            '<!doctype html><meta charset="utf-8"><title>标签多选验证</title><style>body{font:14px system-ui;margin:24px;background:#ebeef3;color:#253047}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:16px}article{background:white;padding:12px;border-radius:8px}img{max-width:100%;max-height:620px}p{margin:12px 0 0}</style>'
            + f"<h1>{args.language} · {args.scale:g}×</h1><main>{cards}</main>",
            encoding="utf-8",
        )
    finally:
        w.stop_directory_load()
        w.shutdown_image_decode_cache()
        w.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
print("LABEL_SELECTION_RENDER_COMPLETE", len(manifest))
