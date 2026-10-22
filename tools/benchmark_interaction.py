"""Reproducible high-resolution UI latency probe (isolated temporary data)."""
from __future__ import annotations

import argparse
import inspect
import json
import os
from pathlib import Path
import statistics
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, Qt, QTimer
from PyQt5.QtGui import QColor, QImage, QMouseEvent, QPixmap
from PyQt5.QtWidgets import QApplication

from labelimg.canvas.widget import Canvas
from labelimg.canvas.shape import Shape
from labelimg.image_tools.application.session import GeometryTransformChange
from labelimg.image_tools.ui.geometry_dialog import GeometryTransformDialog
from labelimg.image_tools.ui.adjustment_dialog import ImageAdjustmentDialog
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


def measure(operation, count):
    samples = []
    for index in range(count):
        start = time.perf_counter()
        operation(index)
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return {"median_ms": round(statistics.median(samples), 2),
            "p95_ms": round(samples[min(len(samples) - 1, int(len(samples) * .95))], 2)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--assert-budget", action="store_true")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temporary:
        os.environ["LABELIMG_CONFIG_DIR"] = temporary
        classes = Path(temporary, "classes.txt")
        classes.write_text("", encoding="utf-8")
        image = QImage(10000, 7000, QImage.Format_RGB32)
        image.fill(QColor(90, 120, 150))
        canvas = Canvas()
        canvas.resize(1400, 980)
        canvas.load_pixmap(QPixmap.fromImage(image))
        canvas.scale = .14
        canvas.set_editing(False)
        canvas.show()
        app.processEvents()

        def move(index):
            point = QPointF(200 + index % 600, 200 + index % 400)
            QApplication.sendEvent(canvas, QMouseEvent(
                QEvent.MouseMove, point, Qt.NoButton, Qt.NoButton, Qt.NoModifier))
            app.processEvents()

        move(0)
        report = {"image_size": [image.width(), image.height()],
                  "crosshair": measure(move, 40)}
        shapes = []
        for index in range(500):
            shape = Shape(label=f'box {index}', paint_label=True)
            x, y = 20 + index % 25 * 350, 20 + index // 25 * 300
            for point in ((x, y), (x + 160, y), (x + 160, y + 180), (x, y + 180)):
                shape.add_point(QPointF(*point))
            shape.close()
            shapes.append(shape)
        canvas.load_shapes(shapes)
        canvas.set_editing(False)
        move(0)
        report['crosshair_500_boxes'] = measure(move, 40)
        QApplication.sendEvent(canvas, QMouseEvent(
            QEvent.MouseButtonPress, QPointF(100, 100),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        move(0)
        report['drawing_500_boxes'] = measure(move, 40)
        canvas.hide()
        canvas.deleteLater()
        paths = []
        for index in range(3):
            path = str(Path(temporary, f"{index}.jpg"))
            image.save(path, quality=90)
            paths.append(path)
        window = create_workbench(WorkbenchLaunchOptions(class_file=str(classes)))
        window.resize(1500, 1000)
        window.show()
        app.processEvents()

        def load(index):
            assert window.load_file(paths[index % len(paths)])
            app.processEvents()

        report["load_cold_and_warm"] = measure(load, 6)
        window.import_dir_images(temporary)
        app.processEvents()
        request_times = []
        gaps = []
        last_tick = time.perf_counter()
        def tick():
            nonlocal last_tick
            now = time.perf_counter()
            gaps.append((now - last_tick) * 1000)
            last_tick = now
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(tick)
        timer.start()
        start = time.perf_counter()
        for _ in range(12):
            for operation in (window.open_next_image, window.open_prev_image):
                request_start = time.perf_counter()
                operation()
                request_times.append((time.perf_counter() - request_start) * 1000)
                app.processEvents()
        deadline = time.perf_counter() + 10
        while getattr(window, '_navigation_load_path', None) and time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(.001)
        app.processEvents()
        timer.stop()
        report['rapid_navigation'] = {
            'requests': len(request_times),
            'request_p95_ms': round(sorted(request_times)[int(len(request_times) * .95)], 2),
            'max_gui_heartbeat_gap_ms': round(max(gaps, default=0), 2),
            'settled_ms': round((time.perf_counter() - start) * 1000, 2),
            'latest_target_reached': window.file_path == paths[0],
        }
        def preview(dialog_type):
            options = {'parent': window}
            if 'preview_image' in inspect.signature(dialog_type).parameters:
                options['preview_image'] = window.image
            dialog = dialog_type(window.file_path, **options)
            dialog.show()
            app.processEvents()
            dialog.reject()
            dialog.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        report['geometry_preview_open'] = measure(lambda _: preview(GeometryTransformDialog), 3)
        report['adjustment_preview_open'] = measure(lambda _: preview(ImageAdjustmentDialog), 3)
        gaps.clear()
        last_tick = time.perf_counter()
        timer.start()
        start = time.perf_counter()
        plan = window.image_processing.prepare(GeometryTransformChange(
            paths=(window.file_path,), operation='rotate-clockwise',
            current_path=window.file_path, preserve_current=True))
        app.processEvents()
        timer.stop()
        report['geometry_preparation'] = {
            'total_ms': round((time.perf_counter() - start) * 1000, 2),
            'max_gui_heartbeat_gap_ms': round(max(gaps, default=0), 2),
            'output_size': list(plan._geometry.targets[0].prepared.snapshot.image_size),
        }
        del plan
        window.shutdown_image_decode_cache()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
    output = json.dumps(report, indent=2)
    print(output, flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    if args.assert_budget:
        for name in ('crosshair', 'crosshair_500_boxes', 'drawing_500_boxes'):
            assert report[name]['p95_ms'] < 1000 / 60, f'{name} misses 60 Hz frame budget'
        assert report['rapid_navigation']['request_p95_ms'] < 25, 'navigation blocks input'
        assert report['rapid_navigation']['latest_target_reached'], 'stale navigation result'


if __name__ == "__main__":
    main()
