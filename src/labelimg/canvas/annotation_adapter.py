"""Project between Qt-free annotation boxes and interactive Canvas shapes."""

try:
    from PyQt5.QtCore import QPointF
    from PyQt5.QtGui import QColor
except ImportError:
    from PyQt4.QtCore import QPointF
    from PyQt4.QtGui import QColor

from labelimg.annotations.domain.model import AnnotationBox, AnnotationDocument
from labelimg.canvas.shape import Shape


def box_from_shape(shape):
    return AnnotationBox(
        label=shape.label,
        points=tuple((point.x(), point.y()) for point in shape.points),
        line_color=(
            shape.line_color.getRgb() if shape.line_color is not None else None
        ),
        fill_color=(
            shape.fill_color.getRgb() if shape.fill_color is not None else None
        ),
        difficult=bool(shape.difficult),
    )


def document_from_shapes(
    image_path,
    image_data,
    shapes,
    class_names=(),
    verified=False,
    questioned=False,
):
    return AnnotationDocument(
        image_path=image_path,
        image_data=image_data,
        boxes=tuple(box_from_shape(shape) for shape in shapes),
        class_names=tuple(class_names),
        verified=bool(verified),
        questioned=bool(questioned),
    )


def shape_from_box(box, snap_point, color_for_label):
    shape = Shape(label=box.label)
    snapped_any = False
    for x, y in box.points:
        x, y, snapped = snap_point(x, y)
        snapped_any = snapped_any or snapped
        shape.add_point(QPointF(x, y))
    shape.difficult = box.difficult
    shape.close()
    shape.line_color = (
        QColor(*box.line_color) if box.line_color else color_for_label(box.label)
    )
    shape.fill_color = (
        QColor(*box.fill_color) if box.fill_color else color_for_label(box.label)
    )
    return shape, snapped_any


def shapes_from_document(document, snap_point, color_for_label):
    shapes = []
    snapped_any = False
    for box in document.boxes:
        shape, snapped = shape_from_box(box, snap_point, color_for_label)
        shapes.append(shape)
        snapped_any = snapped_any or snapped
    return shapes, snapped_any
