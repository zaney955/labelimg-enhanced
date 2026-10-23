"""Render real Qt surfaces at independent application zoom and device scales.

Use --native for Windows window-system verification. Fixtures and preferences
are isolated under --output; no user images, annotations or settings are read.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dpr', type=float, default=1)
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--populated', action='store_true', help='Include annotated fixture files and grouped annotation rows')
    parser.add_argument('--language', choices=('en', 'zh_CN'), default='zh_CN')
    parser.add_argument('--mode', choices=('light', 'dark'), default='light')
    parser.add_argument('--levels', type=int, nargs='+', default=[75, 100, 125, 150, 200])
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    config = root / 'config'
    config.mkdir(exist_ok=True)
    os.environ['LABELIMG_CONFIG_DIR'] = str(config)
    os.environ['QT_SCALE_FACTOR'] = str(args.dpr)
    os.environ['QT_QPA_PLATFORM'] = 'windows' if args.native else 'offscreen'

    from PyQt5.QtCore import QEvent, QPoint, QRect, Qt
    from PyQt5.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QScreen
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication
    from labelimg.ui.appearance import AppearanceDialog
    from labelimg.workbench.bootstrap import create_workbench, WorkbenchLaunchOptions
    from labelimg.workbench.preferences import PreferencesDialog

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([])
    screen_patch = None
    if not args.native:
        # Offscreen defaults to an 800x600 *physical* screen, only 400x300 DIP
        # at DPR 2. Model the same usable logical desktop at every density.
        from unittest.mock import patch
        screen_patch = patch.object(QScreen, 'availableGeometry', lambda _screen: QRect(0, 0, 1600, 1000))
        screen_patch.start()
    exceptions = []

    def exception_hook(*error):
        exceptions.append(''.join(traceback.format_exception(*error)))
    sys.excepthook = exception_hook
    font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    if font_path.is_file():
        fid = QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont(QFontDatabase.applicationFontFamilies(fid)[0], 9))
    image = QImage(1600, 1000, QImage.Format_RGB32)
    image.fill(QColor('#d8dfe5'))
    painter = QPainter(image)
    painter.fillRect(180, 220, 600, 420, QColor('#7a8993'))
    painter.end()
    fixtures = root / 'fixtures'
    fixtures.mkdir(exist_ok=True)
    image_path = fixtures / 'fixture.png' if args.populated else root / 'fixture.png'
    image.save(str(image_path))
    if args.populated:
        from labelimg.annotations.infrastructure.document import AnnotationDocument
        from labelimg.annotations.domain.model import AnnotationBox, AnnotationFormat
        for index in range(3):
            fixture = fixtures / ('fixture.png' if index == 0 else f'image_{index:02d}.png')
            image.save(str(fixture))
            document = AnnotationDocument(str(fixture), image, boxes=(
                AnnotationBox('裂纹', ((220, 260), (450, 260), (450, 430), (220, 430))),
                AnnotationBox('缺损', ((570, 360), (740, 360), (740, 550), (570, 550))),
            ))
            document.save(str(fixture.with_suffix('.xml')), AnnotationFormat.PASCAL_VOC)
    classes = root / 'classes.txt'
    classes.write_text('', encoding='utf-8')
    window = create_workbench(WorkbenchLaunchOptions(class_file=str(classes), save_dir=''))
    window.change_language(args.language)
    window.appearance.apply_preferences(args.mode, 'plum')
    window.resize(1200, 800)
    window.show()
    QTest.qWait(40)
    if args.populated:
        window.import_dir_images(str(fixtures))
    else:
        window.load_file(str(image_path))
    window.set_zoom(100)
    window.candidate_label_dialog.set_candidate_labels(['裂纹', '缺损', 'Long category name', '表面异常'])
    records = []
    issues = []
    window.activateWindow()
    app.setActiveWindow(window)
    QTest.qWait(30)
    QTest.keyClick(window, Qt.Key_Equal, Qt.ControlModifier)
    if window.ui_scale.percent != 110 or window.zoom_widget.value() != 100:
        issues.append('native/global keyboard routing failed')
    QTest.keyClick(window, Qt.Key_0, Qt.ControlModifier)
    QTest.keyClick(window, Qt.Key_Equal, Qt.ControlModifier | Qt.AltModifier)
    if abs(window.zoom_widget.value() - 110) > 0.001 or window.ui_scale.percent != 100:
        issues.append('native/canvas keyboard routing failed')
    window.set_zoom(100)

    def capture(widget, name, percent):
        QTest.qWait(35)
        path = root / f'{percent:03d}-{name}.png'
        widget.grab().save(str(path))
        handle = widget.windowHandle()
        records.append({'name': name, 'percent': percent, 'path': path.name,
                        'size': [widget.width(), widget.height()],
                        'dpr': widget.devicePixelRatioF(),
                        'exposed': bool(handle and handle.isExposed())})

    for percent in args.levels:
        window.ui_scale.set_percent(percent, persist=False)
        QTest.qWait(60)
        capture(window, 'workbench', percent)
        if window.zoom_widget.value() != 100:
            issues.append(f'{percent}: application zoom changed manual image zoom')
        if window.width() > 1200 or window.height() > 800:
            issues.append(f'{percent}: main window grew to {window.width()}x{window.height()}')
        if window.tools.buttons['select'].iconSize().width() != round(24 * percent / 100):
            issues.append(f'{percent}: toolbar icon did not scale')
        window.menus.view.popup(window.mapToGlobal(QPoint(150, 80)))
        capture(window.menus.view, 'view-menu', percent)
        window.menus.view.hide()
        for name, dialog in (
            ('appearance', AppearanceDialog(window.appearance, window)),
            ('preferences', PreferencesDialog(window)),
            ('candidate', window.candidate_label_dialog),
        ):
            dialog.show()
            capture(dialog, name, percent)
            available = dialog.screen().availableGeometry()
            if dialog.width() > available.width() or dialog.height() > available.height():
                issues.append(f'{percent}: {name} exceeds available desktop')
            dialog.hide()
            if name != 'candidate':
                dialog.deleteLater()
        window.activateWindow()
    window.ui_scale.set_percent(100, persist=False)
    window.stop_directory_load()
    window.shutdown_image_decode_cache()
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    manifest = {'language': args.language, 'mode': args.mode,
                'platform': app.platformName(), 'requested_dpr': args.dpr,
                'logical_desktop': None if args.native else [1600, 1000],
                'captures': records, 'issues': issues, 'exceptions': exceptions}
    (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(root), 'captures': len(records), 'issues': issues,
                      'exceptions': len(exceptions)}, ensure_ascii=False), flush=True)
    if screen_patch is not None:
        screen_patch.stop()
    return bool(issues or exceptions)


if __name__ == '__main__':
    raise SystemExit(main())
