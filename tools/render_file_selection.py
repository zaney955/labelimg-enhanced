"""Render and measure file multi-selection using the real styled workbench."""

import argparse
import json
import os
from pathlib import Path
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--scale", type=float, default=1.0)
parser.add_argument("--language", choices=("zh_CN", "en"), default="zh_CN")
args = parser.parse_args()
if args.scale <= 0:
    parser.error("--scale must be positive")
root = args.output.resolve()
root.mkdir(parents=True, exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = str(args.scale)
os.environ["LABELIMG_CONFIG_DIR"] = str(root / "config")
(root / "config").mkdir(exist_ok=True)
from PyQt5.QtCore import QEvent, QRect, Qt
from PyQt5.QtGui import QFont, QFontDatabase, QImage, QColor, QScreen
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from labelimg.platform.settings import Settings
from labelimg.platform.settings_keys import SETTING_AUTO_CHECK_UPDATES
from labelimg.workbench.bootstrap import create_workbench, WorkbenchLaunchOptions
from labelimg.annotations.infrastructure.document import (
    AnnotationDocument,
    AnnotationBox,
)
from labelimg.annotations.domain.model import AnnotationFormat
from labelimg.files.ui.list_widget import (
    FILE_REVIEW_STATE_ROLE,
    FILE_PERSISTENCE_FLAGS_ROLE,
)
from labelimg.ui.theme import COLORS
from labelimg.ui.theme_palettes import available_accents, contrast_ratio

app = QApplication([])
font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
if font_path.is_file():
    fid = QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont(QFontDatabase.applicationFontFamilies(fid)[0], 9))
settings = Settings()
settings[SETTING_AUTO_CHECK_UPDATES] = False
settings.save()
classes = root / "classes.txt"
classes.write_text("", encoding="utf-8")
images = root / "images"
images.mkdir(exist_ok=True)
for i in range(8):
    path = images / f"TXG_ZX_capture3_定位螺栓_20261022001400000_{i+1:03}.png"
    image = QImage(80, 60, QImage.Format_RGB32)
    image.fill(QColor("#74818E"))
    image.save(str(path))
    if i < 6:
        AnnotationDocument(
            str(path),
            image,
            boxes=(AnnotationBox("螺栓", ((10, 10), (40, 10), (40, 35), (10, 35))),),
        ).save(str(path.with_suffix("")), AnnotationFormat.PASCAL_VOC)
manifest = []
with patch.object(QScreen, "availableGeometry", lambda self: QRect(0, 0, 1440, 1000)):
    w = create_workbench(WorkbenchLaunchOptions(class_file=str(classes)))
    w.auto_saving.setChecked(False)
    w.change_language(args.language)
    w.resize(1360, 950)
    w.show()
    w.import_dir_images(str(images))
    app.processEvents()
    w.resizeDocks([w.file_dock], [560], Qt.Horizontal)
    w.resizeDocks([w.file_dock], [580], Qt.Vertical)
    app.processEvents()
    view = w.file_list_widget
    for row in (1, 2, 4, 5):
        view.item(row).setSelected(True)
    view.item(1).setData(FILE_REVIEW_STATE_ROLE, "verified")
    view.item(2).setData(FILE_REVIEW_STATE_ROLE, "questioned")
    view.item(4).setData(FILE_PERSISTENCE_FLAGS_ROLE, ("dirty",))
    view.item(5).setData(FILE_PERSISTENCE_FLAGS_ROLE, ("conflict",))
    selected_before = tuple(w.selected_file_paths())
    current_before = w.file_path
    try:
        for mode in ("light", "dark"):
            for accent in available_accents():
                w.appearance.apply_preferences(mode, accent.identifier)
                for focused in (True, False):
                    (view if focused else w.file_rename_button).setFocus()
                    QTest.mouseMove(w.file_rename_button)
                    app.processEvents()
                    QTest.qWait(15)
                    assert (
                        len(w.selected_file_paths()) == 4
                        and tuple(w.selected_file_paths()) == selected_before
                        and w.file_path == current_before
                    )
                    shot = view.viewport().grab()
                    im = shot.toImage()
                    dpr = shot.devicePixelRatioF()

                    def pixel(x, y):
                        return im.pixelColor(round(x * dpr), round(y * dpr)).name()

                    normal = view.visualItemRect(view.item(3))
                    assert view.viewport().rect().contains(normal)
                    base = pixel(normal.center().x(), normal.bottom() - 5)
                    for row in (1, 2, 4, 5):
                        rect = view.visualItemRect(view.item(row))
                        assert view.viewport().rect().contains(rect)
                        assert (
                            contrast_ratio(
                                pixel(rect.center().x(), rect.bottom() - 5), base
                            )
                            >= 1.15
                        )
                        assert (
                            max(
                                contrast_ratio(
                                    pixel(rect.left() + x, rect.center().y()), base
                                )
                                for x in range(1, 5)
                            )
                            >= 1.45
                        )
                    assert (
                        contrast_ratio(
                            COLORS["selection_foreground"],
                            COLORS["selection_background"],
                        )
                        >= 4.5
                    )
                    assert (
                        contrast_ratio(
                            COLORS["selection_background"], COLORS["surface"]
                        )
                        <= 1.6
                    )
                    assert (
                        contrast_ratio(COLORS["selection_border"], COLORS["surface"])
                        <= 2.2
                    )
                    name = f"{mode}-{accent.identifier}-" + (
                        "list-focus" if focused else "batch-focus"
                    )
                    file = root / (name + ".png")
                    w.file_dock.widget().grab().save(str(file))
                    manifest.append(
                        {
                            "file": str(file),
                            "mode": mode,
                            "accent": accent.identifier,
                            "language": args.language,
                            "scale": args.scale,
                            "focused": focused,
                            "dpr": dpr,
                            "selected": 4,
                            "checks": "passed",
                        }
                    )
    finally:
        w.stop_directory_load()
        w.shutdown_image_decode_cache()
        w.update_ui.close()
        w.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
(root / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("SELECTION_RENDERS_PASSED", len(manifest), flush=True)
