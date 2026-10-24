"""Opt-in Qt interaction benchmark; all file operations use disposable fixtures.

Use --package-root to compare a wheel extraction with the working source tree.
The local rename-based trash adapter measures application overhead, not Windows
Shell or network-drive throughput. Timings include queued Qt paint/layout work.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=3000)
    parser.add_argument('--delete-count', type=int, default=500)
    parser.add_argument('--package-root', type=Path)
    args = parser.parse_args()
    if args.count < 2 or args.delete_count < 1:
        parser.error('counts must be positive; list count must be at least two')
    root = args.package_root or Path(__file__).resolve().parents[1] / 'src'
    sys.path.insert(0, str(root.resolve()))
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt5.QtCore import QEvent, Qt, QPointF
    from PyQt5.QtGui import QColor, QImage, QPixmap
    from PyQt5.QtWidgets import QApplication
    import labelimg
    from labelimg.canvas import Shape
    from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench
    from labelimg.files.ui.list_widget import FileListItem, FILE_ANNOTATION_STATE_ROLE
    from labelimg.platform.recovery import TrashIdentity

    app = QApplication.instance() or QApplication([])
    measurements = {}

    def measure(name, action):
        app.processEvents()
        started = time.perf_counter()
        action()
        app.processEvents()
        measurements[name] = time.perf_counter() - started

    with tempfile.TemporaryDirectory(prefix='labelimg-perf-') as temporary:
        directory = Path(temporary)
        os.environ['LABELIMG_CONFIG_DIR'] = str(directory / 'config')
        classes = directory / 'classes.txt'
        classes.write_text('', encoding='utf8')
        window = create_workbench(WorkbenchLaunchOptions(class_file=str(classes)))
        try:
            window.show()
            window.dir_name = temporary
            window.m_img_list = [str(directory / f'{i:05}.png') for i in range(args.count)]
            items = []
            for i, path in enumerate(window.m_img_list):
                item = FileListItem(os.path.basename(path))
                item.setData(Qt.UserRole, path)
                item.setData(FILE_ANNOTATION_STATE_ROLE, 'annotated' if i % 2 else 'unannotated')
                items.append(item)
            window.file_list_widget.setItems(items)
            window.apply_file_list_view(False)
            measure('annotation_filter', lambda: window.file_list_controls._set_filter('annotated', 'all', 'all'))
            measure('clear_filter', window.file_list_controls.clear_all_conditions)
            measure('select_all', window.file_list_widget.select_all_visible)
            measure('invert_selection', window.file_list_widget.invert_visible_selection)
            measure('state_sort', lambda: window.file_list_controls._set_sort_key('annotation'))
            image = QImage(640, 480, QImage.Format_RGB32)
            image.fill(QColor('white'))
            window.canvas.load_pixmap(QPixmap.fromImage(image))
            shapes = []
            for i in range(500):
                shape = Shape(label='fixture')
                x, y = (i % 25) * 20, (i // 25) * 20
                for px, py in ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)):
                    shape.add_point(QPointF(px, py))
                shape.close()
                shapes.append(shape)
            window.canvas.load_shapes(shapes)
            window.label_list.set_scene(shapes)
            measure('hide_500_annotations', lambda: window.label_visibility_requested(shapes, False))
            measure('show_500_annotations', lambda: window.label_visibility_requested(shapes, True))

            images = directory / 'images'
            trash = directory / 'trash'
            images.mkdir()
            trash.mkdir()
            image = QImage(20, 20, QImage.Format_RGB32)
            image.fill(QColor('white'))
            for i in range(args.delete_count * 2):
                image.save(str(images / f'{i:05}.png'))

            class LocalTrash:
                def move(self, path):
                    target = str(trash / Path(path).name)
                    os.replace(path, target)
                    return TrashIdentity('path', target, path)

            window.canvas.load_shapes([])
            window.system_trash = LocalTrash()
            window.import_dir_images(str(images))
            targets = window.m_img_list[1:args.delete_count + 1]
            results = []
            measure('delete_images', lambda: results.append(window.delete_file_paths(targets)))
            assert len(results[0].succeeded_images) == args.delete_count
            assert all(not Path(path).exists() for path in targets)
        finally:
            window.stop_directory_load()
            window.finish_directory_loads()
            window.finish_deferred_image_loads()
            window.shutdown_image_decode_cache()
            window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
    print(json.dumps({'package': labelimg.__file__, 'python': sys.executable,
                      'list_count': args.count, 'annotation_count': 500,
                      'deleted_count': args.delete_count, 'seconds': measurements}, indent=2))


if __name__ == '__main__':
    main()
