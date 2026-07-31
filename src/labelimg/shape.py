#!/usr/bin/python
# -*- coding: utf-8 -*-

from math import ceil, floor


try:
    from PyQt5.QtGui import *
    from PyQt5.QtCore import *
except ImportError:
    from PyQt4.QtGui import *
    from PyQt4.QtCore import *

from labelimg.utils import distance

DEFAULT_LINE_COLOR = QColor(0, 255, 0, 128)
DEFAULT_FILL_COLOR = QColor(255, 0, 0, 128)
DEFAULT_SELECT_LINE_COLOR = QColor(255, 255, 255)
DEFAULT_SELECT_FILL_COLOR = QColor(0, 128, 255, 155)
DEFAULT_VERTEX_FILL_COLOR = QColor(0, 255, 0, 255)
DEFAULT_HVERTEX_FILL_COLOR = QColor(255, 0, 0)


class Shape(object):
    P_SQUARE, P_ROUND = range(2)

    MOVE_VERTEX, NEAR_VERTEX = range(2)

    # The following class variables influence the drawing
    # of _all_ shape objects.
    line_color = DEFAULT_LINE_COLOR
    fill_color = DEFAULT_FILL_COLOR
    select_line_color = DEFAULT_SELECT_LINE_COLOR
    select_fill_color = DEFAULT_SELECT_FILL_COLOR
    vertex_fill_color = DEFAULT_VERTEX_FILL_COLOR
    h_vertex_fill_color = DEFAULT_HVERTEX_FILL_COLOR
    point_type = P_ROUND
    point_size = 4
    scale = 1.0
    label_font_size = 8
    selected_label_background_color = QColor(0, 0, 0, 153)
    selected_label_text_color = QColor(Qt.white)
    selected_label_padding = 2.0
    selected_label_radius = 2.0
    label_outline_gap = 2.0

    def __init__(self, label=None, line_color=None, difficult=False, paint_label=False):
        # Stable only inside one annotation workspace.  It is deliberately
        # omitted from every persisted annotation format and from copy().
        self.session_id = None
        self.label = label
        self.points = []
        self.fill = False
        self.selected = False
        self.difficult = difficult
        self.paint_label = paint_label

        self._highlight_index = None
        self._highlight_mode = self.NEAR_VERTEX
        self._highlight_settings = {
            self.NEAR_VERTEX: (4, self.P_ROUND),
            self.MOVE_VERTEX: (1.5, self.P_SQUARE),
        }

        self._closed = False

        if line_color is not None:
            # Override the class line_color attribute
            # with an object attribute. Currently this
            # is used for drawing the pending line a different color.
            self.line_color = line_color

    def close(self):
        self._closed = True

    def reach_max_points(self):
        if len(self.points) >= 4:
            return True
        return False

    def add_point(self, point):
        if not self.reach_max_points():
            self.points.append(point)

    def pop_point(self):
        if self.points:
            return self.points.pop()
        return None

    def is_closed(self):
        return self._closed

    def set_open(self):
        self._closed = False

    def paint(self, painter):
        if self.points:
            color = QColor(self.line_color)
            color.setAlpha(255)
            pen = QPen(color)
            pen.setWidthF(1.5 / self.scale)
            painter.setPen(pen)

            line_path = QPainterPath()
            vertex_path = QPainterPath()

            line_path.moveTo(self.points[0])
            # Uncommenting the following line will draw 2 paths
            # for the 1st vertex, and make it non-filled, which
            # may be desirable.
            # self.drawVertex(vertex_path, 0)

            for i, p in enumerate(self.points):
                line_path.lineTo(p)
                self.draw_vertex(vertex_path, i)
            if self.is_closed():
                line_path.lineTo(self.points[0])

            painter.drawPath(line_path)
            painter.drawPath(vertex_path)
            painter.fillPath(vertex_path, color)

            if self.fill:
                fill_color = QColor(
                    self.line_color if self.selected else self.fill_color
                )
                if self.selected:
                    fill_color.setAlpha(100)
                painter.fillPath(line_path, fill_color)

            if self.paint_label:
                self.paint_label_text(painter)

    def paint_label_text(self, painter):
        """Draw label text, highlighting it when this shape is selected."""
        min_x = min(point.x() for point in self.points)
        min_y = min(point.y() for point in self.points)

        if self.label is None:
            self.label = ""
        if not self.label:
            return

        font = QFont()
        font.setPointSize(self.label_font_size)
        font.setBold(True)
        scale = max(float(self.scale), 0.01)
        metrics_rect = QRectF(
            QFontMetrics(font).tightBoundingRect(self.label)
        )
        gap = self.label_outline_gap / scale
        padding = self.selected_label_padding / scale
        text_x = int(round(min_x))
        text_y = int(
            floor(
                min_y
                - gap
                - padding
                - metrics_rect.bottom()
            )
        )
        if metrics_rect.top() + text_y - padding < 0:
            text_y = int(
                ceil(
                    min_y
                    + gap
                    + padding
                    - metrics_rect.top()
                )
            )

        painter.save()
        painter.setFont(font)
        if self.selected:
            text_rect = QRectF(metrics_rect)
            text_rect.translate(text_x, text_y)
            radius = self.selected_label_radius / scale
            background_rect = text_rect.adjusted(
                -padding,
                -padding,
                padding,
                padding,
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.selected_label_background_color)
            painter.drawRoundedRect(background_rect, radius, radius)
            painter.setPen(self.selected_label_text_color)
        painter.drawText(text_x, text_y, self.label)
        painter.restore()

    def draw_vertex(self, path, i):
        d = self.point_size / self.scale
        shape = self.point_type
        point = self.points[i]
        if i == self._highlight_index:
            size, shape = self._highlight_settings[self._highlight_mode]
            d *= size
        if shape == self.P_SQUARE:
            path.addRect(point.x() - d / 2, point.y() - d / 2, d, d)
        elif shape == self.P_ROUND:
            path.addEllipse(point, d / 2.0, d / 2.0)
        else:
            assert False, "unsupported vertex shape"

    def nearest_vertex(self, point, epsilon):
        for i, p in enumerate(self.points):
            if distance(p - point) <= epsilon:
                return i
        return None

    def contains_point(self, point):
        return self.make_path().contains(point)

    def make_path(self):
        path = QPainterPath(self.points[0])
        for p in self.points[1:]:
            path.lineTo(p)
        return path

    def bounding_rect(self):
        return self.make_path().boundingRect()

    def move_by(self, offset):
        self.points = [p + offset for p in self.points]

    def move_vertex_by(self, i, offset):
        self.points[i] = self.points[i] + offset

    def highlight_vertex(self, i, action):
        self._highlight_index = i
        self._highlight_mode = action

    def highlight_clear(self):
        self._highlight_index = None

    def copy(self):
        shape = Shape("%s" % self.label)
        shape.points = [QPointF(p) for p in self.points]
        shape.fill = self.fill
        shape.selected = self.selected
        shape._closed = self._closed
        if self.line_color != Shape.line_color:
            shape.line_color = QColor(self.line_color)
        if self.fill_color != Shape.fill_color:
            shape.fill_color = QColor(self.fill_color)
        shape.difficult = self.difficult
        shape.paint_label = self.paint_label
        return shape

    def __len__(self):
        return len(self.points)

    def __getitem__(self, key):
        return self.points[key]

    def __setitem__(self, key, value):
        self.points[key] = value
