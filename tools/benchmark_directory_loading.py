"""Opt-in large-directory benchmark for the real offscreen workbench."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PyQt5.QtCore import QEvent, QEventLoop, QTimer
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QApplication

from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


def copy_many(source, directory, suffix, count):
    for index in range(count):
        shutil.copyfile(source, directory / f"image_{index:05d}{suffix}")


def elapsed(operation):
    started = time.perf_counter()
    result = operation()
    return time.perf_counter() - started, result


def wait_until(app, predicate, timeout_seconds=30):
    loop = QEventLoop()
    poll = QTimer()
    timeout = QTimer()
    poll.setInterval(5)
    timeout.setSingleShot(True)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    timeout.timeout.connect(loop.quit)
    poll.start()
    timeout.start(int(timeout_seconds * 1000))
    loop.exec_()
    poll.stop()
    app.processEvents()
    return predicate()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10_000)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temporary_name:
        temporary = Path(temporary_name)
        os.environ["LABELIMG_CONFIG_DIR"] = str(temporary / "config")
        images = temporary / "images"
        annotations = temporary / "annotations"
        images.mkdir()
        annotations.mkdir()
        source_image = temporary / "source.png"
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(QColor("white"))
        image.save(str(source_image))
        source_annotation = temporary / "source.xml"
        source_annotation.write_text(
            "<annotation><filename>image.png</filename>"
            "<object><name>fixture</name><bndbox><xmin>1</xmin><ymin>1</ymin>"
            "<xmax>4</xmax><ymax>4</ymax></bndbox></object></annotation>",
            encoding="utf-8",
        )
        copy_many(source_image, images, ".png", args.count)
        copy_many(source_annotation, annotations, ".xml", args.count)
        classes = temporary / "classes.txt"
        classes.write_text("", encoding="utf-8")
        window = create_workbench(WorkbenchLaunchOptions(
            class_file=str(classes), save_dir=str(annotations)
        ))

        synchronous, _ = elapsed(lambda: window.import_dir_images(str(images)))
        annotation_switch, switched = elapsed(
            lambda: window._switch_annotation_directory(str(annotations))
        )

        ready_started = time.perf_counter()
        window.dir_name = None
        window.start_directory_load(str(images))
        ready = wait_until(app, lambda: window.dir_name == str(images))
        ready_seconds = time.perf_counter() - ready_started
        complete_started = ready_started
        complete = wait_until(app, lambda: not window._directory_load_jobs)
        if complete:
            complete = wait_until(
                app,
                lambda: not window._directory_projection_pending,
            )
        complete_seconds = time.perf_counter() - complete_started

        print(f"files={args.count}")
        print(f"synchronous_open_seconds={synchronous:.3f}")
        print(f"annotation_switch_seconds={annotation_switch:.3f}")
        print(f"async_directory_ready_seconds={ready_seconds:.3f} ready={ready}")
        print(f"async_index_complete_seconds={complete_seconds:.3f} complete={complete}")
        print(
            "directory_ready_ui_task_seconds="
            f"{window._directory_ready_commit_seconds:.3f}"
        )
        print(
            "max_ui_batch_seconds="
            f"{window._directory_max_ui_batch_seconds:.3f}"
        )
        print(f"annotation_switched={switched}")
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
    return 0 if ready and complete and switched else 1


if __name__ == "__main__":
    raise SystemExit(main())
