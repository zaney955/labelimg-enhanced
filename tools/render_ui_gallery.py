"""Reproducible bilingual Qt UI gallery; never opens user data or applies edits."""

from pathlib import Path
import json, os, sys
from types import SimpleNamespace
from html import escape
from unittest.mock import PropertyMock, patch

import argparse

parser = argparse.ArgumentParser(
    description="Render the real Qt workbench and dialogs with disposable fixtures."
)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--language", choices=("en", "zh_CN"), default="zh_CN")
parser.add_argument("--scale", type=float, default=1.0)
args = parser.parse_args()
if args.scale <= 0:
    parser.error("--scale must be positive")
ROOT = args.output.resolve()
ROOT.mkdir(parents=True, exist_ok=True)
os.environ["QT_SCALE_FACTOR"] = str(args.scale)
(ROOT / "config").mkdir(exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LABELIMG_CONFIG_DIR"] = str(ROOT / "config")
from PyQt5.QtCore import QEvent, QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen, QScreen
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QScrollArea,
    QMessageBox,
    QLabel,
)
from PyQt5.QtTest import QTest
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench
from labelimg.annotations.infrastructure.document import (
    AnnotationDocument,
    AnnotationBox,
)
from labelimg.annotations.domain.model import AnnotationFormat
from labelimg.annotations.ui.candidate_label_dialog import CandidateLabelDialog
from labelimg.annotations.ui.label_color_palette_dialog import LabelColorPaletteDialog
from labelimg.annotations.ui.label_replace_dialog import LabelReplaceDialog
from labelimg.annotations.ui.statistics_dialog import AnnotationStatisticsDialog
from labelimg.annotations.ui.near_duplicate_chooser import NearDuplicateChooser
from labelimg.annotations.application.persistence import ExternalAnnotationConflict
from labelimg.annotations.application.statistics import AnnotationStatisticsCollector
from labelimg.files.ui.cleanup_dialog import AnnotationCleanupDialog
from labelimg.files.ui.list_widget import BatchRenameDialog
from labelimg.image_tools.ui.quality_panel import ImageQualityDialog, ImageQualityPanel
from labelimg.image_tools.ui.geometry_dialog import GeometryTransformDialog
from labelimg.image_tools.ui.adjustment_dialog import ImageAdjustmentDialog
from labelimg.image_tools.ui.colored_frame_dialog import ImageToolsDialog
from labelimg.image_tools.ui.recovery_dialog import ImageRecoverySelectionDialog
from labelimg.workbench.help_ui import ShortcutCatalogDialog, AboutDialog
from labelimg.workbench.annotation_display import show_annotation_display_settings
from labelimg.updates.ui.notification import UpdateCenterWindow
from labelimg import __version__
from labelimg.localization.runtime import localize_message_box_buttons, tr

app = QApplication.instance() or QApplication([])
font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
if font_path.is_file():
    fid = QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont(QFontDatabase.applicationFontFamilies(fid)[0], 9))
elif not QFontDatabase().families():
    raise RuntimeError("Rendering requires a real UI font")
# The offscreen plugin defaults to 800x600. Model a 1920x1080 desktop at
# the requested DPR while retaining Qt's real scale-dependent rendering.
virtual_screen = QRect(0, 0, round(1920 / args.scale), round(1080 / args.scale))
screen_patch = patch.object(QScreen, "availableGeometry", lambda self: virtual_screen)
screen_patch.start()
images = ROOT / "images"
annotations = ROOT / "labels"
images.mkdir(exist_ok=True)
annotations.mkdir(exist_ok=True)
classes = ROOT / "empty-classes.txt"
classes.write_text("", encoding="utf-8")
paths = []
for i in range(4):
    path = images / f"sample_{i+1:02}.png"
    paths.append(str(path))
    image = QImage(720, 480, QImage.Format_RGB32)
    image.fill(QColor("#D9DEE4"))
    painter = QPainter(image)
    painter.setPen(QPen(QColor("#BDC5CF"), 1))
    for x in range(0, 720, 40):
        painter.drawLine(x, 0, x, 480)
    for y in range(0, 480, 40):
        painter.drawLine(0, y, 720, y)
    painter.setBrush(QColor("#737F8A"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(100, 100, 480, 280, 16, 16)
    painter.setPen(QPen(QColor("#B2BAC5"), 10))
    painter.drawLine(180, 160, 260, 240)
    painter.drawLine(260, 240, 310, 220)
    painter.end()
    image.save(str(path))
    if i < 3:
        boxes = (
            AnnotationBox("裂纹", ((160, 140), (330, 140), (330, 270), (160, 270))),
        )
        if i == 1:
            boxes += (
                AnnotationBox("缺损", ((420, 220), (530, 220), (530, 320), (420, 320))),
            )
        AnnotationDocument(str(path), image, boxes=boxes).save(
            str(annotations / path.stem), AnnotationFormat.PASCAL_VOC
        )
window = create_workbench(
    WorkbenchLaunchOptions(class_file=str(classes), save_dir=str(annotations))
)
window.auto_saving.setChecked(False)
window.change_language(args.language)
window.resize(min(1440, virtual_screen.width()), min(900, virtual_screen.height()))
window.show()
app.processEvents()
manifest = []
widgets = []


def capture(name, widget, hide=True):
    if widget not in widgets:
        widgets.append(widget)
    # Qt's Windows offscreen plugin crashes while exposing QMessageBox even
    # without application styles. Render its real hidden controls instead.
    hidden_render = isinstance(widget, QMessageBox)
    if hidden_render:
        text = widget.findChild(QLabel, "qt_msgbox_label")
        if text is not None:
            text.setWordWrap(True)
            text.setFixedWidth(min(480, max(100, virtual_screen.width() - 150)))
            text.setFixedHeight(text.heightForWidth(text.width()))
        widget.ensurePolished()
        widget.adjustSize()
        widget.setFixedSize(widget.layout().totalSizeHint())
        widget.layout().setGeometry(widget.rect())
    else:
        widget.show()
        app.processEvents()
        QTest.qWait(80)
    # Check the real projected widget geometry, not a mock layout model.
    problems = []
    if isinstance(widget, QDialog) and getattr(widget, "_presentation_chrome", None):
        if (
            widget.width() > virtual_screen.width() - 24
            or widget.height() > virtual_screen.height() - 24
        ):
            problems.append("dialog exceeds available desktop")
        for box in widget.findChildren(QDialogButtonBox):
            if not box.isVisible():
                continue
            if any(
                box.isAncestorOf(other)
                for other in widget.findChildren(QDialogButtonBox)
                if other is not box
            ):
                continue
            point = box.mapTo(widget, QPoint())
            if point.y() < 0 or point.y() + box.height() > widget.height():
                problems.append("footer outside dialog")
            if any(area.isAncestorOf(box) for area in widget.findChildren(QScrollArea)):
                problems.append("footer scrolls with body")
    if problems:
        raise AssertionError(name + ": " + ", ".join(problems))
    file = ROOT / (name + ".png")
    widget.grab().save(str(file))
    manifest.append(
        {
            "name": name,
            "title": widget.windowTitle(),
            "width": widget.width(),
            "height": widget.height(),
            "file": str(file),
            "language": args.language,
            "scale": args.scale,
            "geometry_checks": "passed",
            "render_method": "hidden-widget" if hidden_render else "shown-widget",
            "device_pixel_ratio": widget.devicePixelRatioF(),
        }
    )
    print(name, widget.width(), widget.height(), flush=True)
    if hide:
        widget.hide()


def intercepted(name, invoke):
    def grab(dialog):
        capture(name, dialog)
        return QDialog.Rejected

    with patch.object(QDialog, "exec_", grab):
        invoke()


try:
    capture("37-empty-workbench", window, False)
    window.import_dir_images(str(images))
    app.processEvents()
    capture("01-workbench", window, False)
    controls = window.file_list_controls
    controls.set_category_filter({"裂纹", "缺损"}, "any")
    controls.filter_panel.show_for(controls.filter_button)
    capture("02-filter-reference", controls.filter_panel)
    controls.clear_all_conditions()
    capture(
        "03-candidate-reference",
        CandidateLabelDialog(
            parent=window,
            list_item=["裂纹", "缺损", "异物"],
            color_for_label=window.label_color_palette.color,
        ),
    )
    intercepted(
        "04-annotation-display", lambda: show_annotation_display_settings(window)
    )
    capture(
        "05-batch-rename",
        BatchRenameDialog(paths, str(images), str(annotations), window),
    )
    replace = LabelReplaceDialog(
        ["裂纹", "缺损"],
        selected_count=2,
        preview=lambda scope, old, new, progress: window.label_replacement.preview(
            paths if scope == "all" else paths[:2],
            old,
            new,
            AnnotationFormat.PASCAL_VOC,
            progress=progress,
        ),
        parent=window,
    )
    replace.old_label.setCurrentText("裂纹")
    replace.new_label.setText("裂缝")
    replace.preview()
    capture("06-label-replace", replace)
    palette = LabelColorPaletteDialog(
        ["裂纹", "缺损", "异物"],
        window.label_color_palette,
        window.color_dialog,
        window,
    )
    capture("07-color-palette", palette)
    capture(
        "08-quality-settings", ImageQualityDialog(paths[0], paths[:2], paths, window)
    )
    geometry = GeometryTransformDialog(
        paths[0], paths[:2], workspace_paths=paths, parent=window
    )
    capture("09-geometry", geometry)
    capture(
        "10-pixel-adjustment",
        ImageAdjustmentDialog(
            paths[0], paths[:2], parent=window, workspace_paths=paths
        ),
    )
    frame = ImageToolsDialog(
        paths[0],
        paths[:2],
        workspace_paths=paths,
        commit=lambda *_args: None,
        asynchronous=False,
        parent=window,
    )
    capture("11-colored-frame", frame)
    stats = AnnotationStatisticsDialog(
        lambda progress: AnnotationStatisticsCollector(
            window.annotation_workspace, window.annotation_editing
        ).collect(paths, progress),
        image_dir=str(images),
        annotation_dir=str(annotations),
        color_for_label=window.label_color_palette.color,
        parent=window,
    )
    stats.refresh()
    capture("12-statistics", stats)
    cleanup = AnnotationCleanupDialog(str(images), str(annotations), (".png",), window)
    cleanup.scan()
    capture("13-cleanup", cleanup)
    capture(
        "14-recovery-selection",
        ImageRecoverySelectionDialog(
            [SimpleNamespace(original_path=p) for p in paths[:2]], window
        ),
    )
    intercepted("15-recovery-center", window.open_file_recovery_center)
    capture("16-shortcuts", ShortcutCatalogDialog(window))
    capture(
        "17-about",
        AboutDialog("LabelImg Enhanced", __version__, sys.version.split()[0], window),
    )
    window.display_adjustment_overlay.open()
    capture(
        "18-display-adjustment-reference", window.display_adjustment_overlay.panel_shell
    )
    update = UpdateCenterWindow()
    update.show_up_to_date(__version__)
    capture("19-update-center", update)
    with patch.object(window.candidate_label_dialog, "choose", return_value="新裂纹"):
        window.edit_shape_label(window.canvas.shapes[0])
    intercepted("20-unsaved-annotations", window.may_continue)
    window.undo_annotation()
    capture("21-color-picker", window.color_dialog)
    first = window.canvas.shapes[0]
    second = first.copy()
    duplicate = NearDuplicateChooser(window)
    duplicate.show_cluster(
        SimpleNamespace(members=(first, second), risk="duplicate"), (first, second)
    )
    capture("22-near-duplicate", duplicate)
    resource = str(annotations / "sample_01.xml")
    with patch.object(
        type(window.annotation_persistence),
        "conflicts",
        new_callable=PropertyMock,
        return_value={
            resource: ExternalAnnotationConflict(
                resource, Exception("Example external edit")
            )
        },
    ):
        intercepted("23-external-conflicts", window._resolve_conflicts_for_close)
    # Results are a presentation projection; quality analysis remains read-only.
    results = ImageQualityPanel(window)
    results.resize(720, 340)
    capture("24-quality-results", results)
    frame.advanced_toggle.setChecked(True)
    capture("25-colored-frame-advanced", frame)
    for index, action in enumerate(window.menuBar().actions(), 26):
        menu = action.menu()
        if menu is not None:
            menu.popup(window.mapToGlobal(QPoint(20, 50)))
            capture(f"{index:02}-menu", menu)
    from labelimg.image_tools.application.geometry_transform import GeometryOperation

    geometry.operation_combo.setCurrentIndex(
        geometry.operation_combo.findData(GeometryOperation.RESIZE)
    )
    capture("33-geometry-resize", geometry)
    frame.result_tabs.setCurrentIndex(1)
    capture("34-colored-frame-targets", frame)
    message = QMessageBox(
        QMessageBox.Warning,
        tr("labelReplace.title"),
        tr("ui.replace.commitHint"),
        QMessageBox.Ok,
        window,
    )
    localize_message_box_buttons(message)
    capture("35-message-box", message)
    window.image_quality_dock.show()
    capture("36-quality-dock", window.image_quality_dock)
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cards = "".join(
        f'<article><a href="{escape(Path(entry["file"]).name)}">'
        f'<img loading="lazy" src="{escape(Path(entry["file"]).name)}"></a>'
        f'<p>{escape(entry["name"])} · {entry["width"]}×{entry["height"]}</p></article>'
        for entry in manifest
    )
    (ROOT / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Qt UI gallery</title>'
        "<style>body{font:14px system-ui;background:#f5f6f9;color:#253047;margin:24px}"
        "main{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:20px}"
        "article{background:white;border:1px solid #d7dee8;border-radius:8px;padding:12px}"
        "img{width:100%;height:320px;object-fit:contain}p{margin:10px 0 0}</style>"
        f"<h1>{args.language} · {args.scale:g}×</h1><p>Real Qt widgets · Offscreen render · Click to inspect</p>"
        f"<main>{cards}</main>",
        encoding="utf-8",
    )
finally:
    for widget in widgets:
        if widget is not window:
            try:
                widget.hide()
                widget.deleteLater()
            except RuntimeError:
                pass
    window.stop_directory_load()
    window.shutdown_image_decode_cache()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
screen_patch.stop()
print("CAPTURE_COMPLETE", len(manifest))
