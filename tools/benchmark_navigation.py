"""Opt-in real-image navigation benchmark; source images are read-only.

Set QT_QPA_PLATFORM=windows for native Windows painting, or offscreen for CI.
Settings, labels and class mappings are isolated in a temporary directory.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import tempfile
import time

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import QFont, QFontDatabase, QKeyEvent
from PyQt5.QtWidgets import QApplication
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


def distribution(values):
    ordered = sorted(values)
    return {'count': len(values), 'median_ms': statistics.median(ordered),
            'p95_ms': ordered[min(len(ordered) - 1, int(len(ordered) * .95))],
            'max_ms': max(ordered)} if values else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--count', type=int, default=40)
    parser.add_argument('--start-prefix', help='Begin at the first naturally sorted matching filename')
    parser.add_argument('--preview-cache-dir', type=Path, help='Explicit persistent preview cache for repeat runs')
    parser.add_argument('--prepare-previews', action='store_true', help='Wait for background PNG previews before measuring')
    parser.add_argument('--gesture', choices=('hold', 'tap'), default='tap')
    parser.add_argument('--interval-ms', type=int)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--screenshot', type=Path)
    parser.add_argument('--max-gap-ms', type=float, default=300)
    args = parser.parse_args()
    if args.preview_cache_dir:
        os.environ['LABELIMG_PREVIEW_CACHE_DIR'] = str(args.preview_cache_dir.resolve())
    interval = args.interval_ms or (33 if args.gesture == 'hold' else 100)
    app = QApplication.instance() or QApplication([])
    font = Path('C:/Windows/Fonts/msyh.ttc')
    if font.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font))
        app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 9))
    records, heartbeat, requests = [], [], {}
    phase = None
    last_painted = None
    last_frame = time.perf_counter()
    last_tick = last_frame
    preparation_ms = None
    previous_config = os.environ.get('LABELIMG_CONFIG_DIR')
    with tempfile.TemporaryDirectory(prefix='labelimg-nav-benchmark-') as temp:
        os.environ['LABELIMG_CONFIG_DIR'] = temp
        classes = Path(temp, 'classes.txt'); classes.write_text('')
        labels = Path(temp, 'labels'); labels.mkdir()
        window = create_workbench(WorkbenchLaunchOptions(class_file=str(classes), save_dir=str(labels)))
        try:
            window.resize(1200, 800); window.show(); app.processEvents()
            window.import_dir_images(str(args.directory.resolve()))
            window.stop_directory_load()
            if args.prepare_previews:
                preparation_started = time.perf_counter()
                deadline = time.perf_counter() + 300
                warmup = window._ensure_image_decode_cache()._warmup
                while not warmup.wait(0) and time.perf_counter() < deadline:
                    app.processEvents(); time.sleep(.01)
                if not warmup.wait(0):
                    raise AssertionError('PNG preview preparation did not finish')
                preparation_ms = (time.perf_counter() - preparation_started) * 1000
            if not window.file_path or len(window.m_img_list) < 2:
                raise ValueError('benchmark requires at least two readable images')
            start = 0
            if args.start_prefix:
                start = next(index for index, path in enumerate(window.m_img_list)
                             if Path(path).name.startswith(args.start_prefix))
                window._load_indexed_image(window.m_img_list[start])
            count = min(args.count, len(window.m_img_list) - start - 1)
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            window.activateWindow(); window.canvas.setFocus(); app.processEvents()
            request = window._request_indexed_image
            paint = window.canvas.paintEvent

            def requested(path):
                requests.setdefault(path, time.perf_counter())
                return request(path)

            def painted(event):
                nonlocal last_painted, last_frame
                paint(event)
                path = window.file_path
                if phase is not None and path != last_painted:
                    now = time.perf_counter()
                    records.append({'phase': phase, 'index': window.cur_img_idx,
                                    'interval_ms': (now - last_frame) * 1000,
                                    'latency_ms': (now - requests.pop(path, now)) * 1000})
                    last_painted, last_frame = path, now

            def tick():
                nonlocal last_tick
                now = time.perf_counter()
                heartbeat.append((now - last_tick) * 1000)
                last_tick = now

            window._request_indexed_image = requested
            window.canvas.paintEvent = painted
            last_tick = time.perf_counter()
            pulse = QTimer(); pulse.setInterval(5); pulse.timeout.connect(tick); pulse.start()
            # Start immediately: include cold directory-entry prefetch behavior.
            for key, text, target in ((Qt.Key_D, 'd', start + count), (Qt.Key_A, 'a', start)):
                phase, last_painted, last_frame = text, window.file_path, time.perf_counter()
                requests.clear()
                timer = QTimer(); timer.setInterval(interval)

                def press():
                    if (text == 'd' and window.cur_img_idx >= target
                            or text == 'a' and window.cur_img_idx <= target):
                        return
                    QApplication.sendEvent(window.canvas, QKeyEvent(
                        QEvent.KeyPress, key, Qt.NoModifier, text, args.gesture == 'hold'))
                    if args.gesture == 'tap':
                        QApplication.sendEvent(window.canvas, QKeyEvent(
                            QEvent.KeyRelease, key, Qt.NoModifier, text))

                timer.timeout.connect(press); timer.start(); press()
                deadline = time.perf_counter() + 60
                while time.perf_counter() < deadline:
                    app.processEvents()
                    if records and records[-1]['phase'] == text and records[-1]['index'] == target:
                        break
                    time.sleep(.001)
                timer.stop()
                QApplication.sendEvent(window.canvas, QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier, text))
                expected = (list(range(start + 1, start + count + 1)) if text == 'd'
                            else list(range(start + count - 1, start - 1, -1)))
                actual = [row['index'] for row in records if row['phase'] == text]
                if actual != expected:
                    raise AssertionError(f'painted sequence differs: {actual} != {expected}')
                phase = None
            pulse.stop()
            # Verify the settled image reaches original resolution.
            deadline = time.perf_counter() + 10
            has_preview = getattr(window, '_has_image_preview', lambda: False)
            while has_preview() and time.perf_counter() < deadline:
                app.processEvents(); time.sleep(.002)
            if has_preview():
                raise AssertionError('settled image did not reach original resolution')
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(args.screenshot))
            cache = window._ensure_image_decode_cache()
            report = {'gesture': args.gesture, 'interval_ms': interval, 'platform': app.platformName(),
                      'directory': str(args.directory.resolve()), 'start_prefix': args.start_prefix,
                      'preparation_ms': preparation_ms,
                      'paint_latency': distribution([row['latency_ms'] for row in records]),
                      'paint_intervals': distribution([row['interval_ms'] for row in records]),
                      'heartbeat': distribution(heartbeat), 'frames': records,
                      'final_dimensions': [window.image.width(), window.image.height()],
                      'preview_budget_mib': cache._max_bytes / 1024**2,
                      'full_budget_mib': getattr(getattr(cache, '_full', None), '_max_bytes', 0) / 1024**2}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2), encoding='utf8')
            print(json.dumps({key: value for key, value in report.items() if key != 'frames'}, indent=2))
            if report['paint_intervals']['max_ms'] > args.max_gap_ms:
                raise AssertionError('painted frame interval exceeds the requested limit')
        finally:
            window.shutdown_image_decode_cache(); window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete); app.processEvents()
            if previous_config is None:
                os.environ.pop('LABELIMG_CONFIG_DIR', None)
            else:
                os.environ['LABELIMG_CONFIG_DIR'] = previous_config


if __name__ == '__main__':
    main()
