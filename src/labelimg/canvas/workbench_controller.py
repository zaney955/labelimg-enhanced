"""CanvasActionsMixin extracted from the top-level workbench window."""

#!/usr/bin/env python
# -*- coding: utf-8 -*-


from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QWidget

import labelimg.ui.generated_resources  # noqa: F401 - registers Qt resources
from labelimg.ui.actions import set_action_copy
from labelimg.canvas.shape import Shape, DEFAULT_LINE_COLOR, DEFAULT_FILL_COLOR
from labelimg.localization.runtime import tr
from labelimg.canvas.widget import Canvas


class CanvasActionsMixin:
    def create_shape(self):
        self.canvas.set_mode(Canvas.CREATE)
        self.actions.create.setChecked(True)
        self.actions.create.setEnabled(False)


    def toggle_drawing_sensitive(self, drawing=True):
        """In the middle of drawing, toggling between modes should be disabled."""
        self.actions.selectTool.setEnabled(not drawing)
        self.actions.panTool.setEnabled(not drawing)
        self.actions.cropImage.setEnabled(not drawing)
        if not drawing:
            self.set_edit_mode()


    def set_edit_mode(self):
        self.canvas.set_mode(Canvas.EDIT)
        self.actions.selectTool.setChecked(True)
        self.actions.create.setEnabled(bool(self.file_path))
        self.label_selection_changed()


    def set_pan_mode(self):
        self.canvas.set_mode(Canvas.PAN)
        self.actions.panTool.setChecked(True)


    def copy_selected_shape(self):
        copied_shapes = self._perform_annotation_edit(
            'Duplicate boxes',
            self.canvas.copy_selected_shapes,
            affected=lambda shapes: shapes,
        )
        if not copied_shapes:
            return
        for shape in copied_shapes:
            self.add_label(shape)
        self.shape_selection_changed(True)
        self.status(tr('status.duplicated', count=len(copied_shapes)))


    def scroll_request(self, delta, orientation):
        units = - delta / (8 * 15)
        bar = self.scroll_bars[orientation]
        bar.setValue(int(round(bar.value() + bar.singleStep() * units)))


    def pan_request(self, delta_x, delta_y):
        horizontal = self.scroll_bars[Qt.Horizontal]
        vertical = self.scroll_bars[Qt.Vertical]
        horizontal.setValue(horizontal.value() - delta_x)
        vertical.setValue(vertical.value() - delta_y)


    def set_zoom(self, value):
        self.actions.fitWidth.setChecked(False)
        self.actions.fitWindow.setChecked(False)
        self.zoom_mode = self.MANUAL_ZOOM
        self.zoom_widget.setValue(int(round(value)))


    def add_zoom(self, increment=10):
        self.set_zoom(self.zoom_widget.value() + increment)


    def zoom_request(self, delta):
        # get the current scrollbar positions
        # calculate the percentages ~ coordinates
        h_bar = self.scroll_bars[Qt.Horizontal]
        v_bar = self.scroll_bars[Qt.Vertical]

        # get the current maximum, to know the difference after zooming
        h_bar_max = h_bar.maximum()
        v_bar_max = v_bar.maximum()

        # get the cursor position and canvas size
        # calculate the desired movement from 0 to 1
        # where 0 = move left
        #       1 = move right
        # up and down analogous
        cursor = QCursor()
        pos = cursor.pos()
        relative_pos = QWidget.mapFromGlobal(self, pos)

        cursor_x = relative_pos.x()
        cursor_y = relative_pos.y()

        w = self.scroll_area.width()
        h = self.scroll_area.height()

        # the scaling from 0 to 1 has some padding
        # you don't have to hit the very leftmost pixel for a maximum-left movement
        margin = 0.1
        move_x = (cursor_x - margin * w) / (w - 2 * margin * w)
        move_y = (cursor_y - margin * h) / (h - 2 * margin * h)

        # clamp the values from 0 to 1
        move_x = min(max(move_x, 0), 1)
        move_y = min(max(move_y, 0), 1)

        # zoom in
        units = delta / (8 * 15)
        scale = 10
        self.add_zoom(scale * units)

        # get the difference in scrollbar values
        # this is how far we can move
        d_h_bar_max = h_bar.maximum() - h_bar_max
        d_v_bar_max = v_bar.maximum() - v_bar_max

        # get the new scrollbar values
        new_h_bar_value = h_bar.value() + move_x * d_h_bar_max
        new_v_bar_value = v_bar.value() + move_y * d_v_bar_max

        h_bar.setValue(int(round(new_h_bar_value)))
        v_bar.setValue(int(round(new_v_bar_value)))


    def set_fit_window(self, value=True):
        if value:
            self.actions.fitWidth.setChecked(False)
        self.zoom_mode = self.FIT_WINDOW if value else self.MANUAL_ZOOM
        self.adjust_scale()


    def set_fit_width(self, value=True):
        if value:
            self.actions.fitWindow.setChecked(False)
        self.zoom_mode = self.FIT_WIDTH if value else self.MANUAL_ZOOM
        self.adjust_scale()


    def toggle_polygons(self, value):
        self.label_visibility_requested(tuple(self.canvas.shapes), value)


    def toggle_all_annotations(self, visible):
        """Apply one explicit all-visible state from the annotation header."""
        self.toggle_polygons(bool(visible))
        action = self.actions.toggleVisibility
        if visible:
            set_action_copy(
                action,
                tr('hideAllBox'),
                tr('hideAllBoxDetail'),
            )
        else:
            set_action_copy(
                action,
                tr('showAllBox'),
                tr('showAllBoxDetail'),
            )


    def resizeEvent(self, event):
        if self.canvas and not self.image.isNull()\
           and self.zoom_mode != self.MANUAL_ZOOM:
            self.adjust_scale()
        super().resizeEvent(event)


    def paint_canvas(self):
        assert not self.image.isNull(), "cannot paint null image"
        self.canvas.scale = 0.01 * self.zoom_widget.value()
        self.canvas.label_font_size = int(0.02 * max(self.image.width(), self.image.height()))
        self.canvas.adjustSize()
        self.canvas.update()


    def adjust_scale(self, initial=False):
        value = self.scalers[self.FIT_WINDOW if initial else self.zoom_mode]()
        self.zoom_widget.setValue(int(100 * value))


    def scale_fit_window(self):
        """Figure out the size of the pixmap in order to fit the main widget."""
        e = 2.0  # So that no scrollbars are generated.
        w1 = self.centralWidget().width() - e
        h1 = self.centralWidget().height() - e
        a1 = w1 / h1
        # Calculate a new scale value based on the pixmap's aspect ratio.
        w2 = self.canvas.pixmap.width() - 0.0
        h2 = self.canvas.pixmap.height() - 0.0
        a2 = w2 / h2
        return w1 / w2 if a2 >= a1 else h1 / h2


    def scale_fit_width(self):
        # The epsilon does not seem to work too well here.
        w = self.centralWidget().width() - 2.0
        return w / self.canvas.pixmap.width()


    def choose_color1(self):
        color = self.color_dialog.getColor(self.line_color, tr('color.chooseLine'),
                                           default=DEFAULT_LINE_COLOR)
        if color:
            self.line_color = color
            Shape.line_color = color
            self.canvas.set_drawing_color(color)
            self.canvas.update()


    def delete_selected_shape(self):
        self.delete_annotation_shapes(
            tuple(self.canvas.selected_shapes),
            'Delete boxes',
        )


    def choose_shape_line_color(self):
        selection = self.canvas.selection_snapshot
        if not selection.capabilities.can_edit_single:
            return
        color = self.color_dialog.getColor(self.line_color, tr('color.chooseLine'),
                                           default=DEFAULT_LINE_COLOR)
        if color and color != selection.active.line_color:
            shape = selection.active
            self._perform_annotation_edit(
                'Change box line color',
                lambda: setattr(shape, 'line_color', color),
                affected=(shape,),
            )
            self.label_list.refresh_shape(shape)
            self.canvas.update()


    def choose_shape_fill_color(self):
        selection = self.canvas.selection_snapshot
        if not selection.capabilities.can_edit_single:
            return
        color = self.color_dialog.getColor(self.fill_color, tr('color.chooseFill'),
                                           default=DEFAULT_FILL_COLOR)
        if color and color != selection.active.fill_color:
            shape = selection.active
            self._perform_annotation_edit(
                'Change box fill color',
                lambda: setattr(shape, 'fill_color', color),
                affected=(shape,),
            )
            self.canvas.update()


    def copy_shape(self):
        self._perform_annotation_edit(
            'Copy box',
            lambda: self.canvas.end_move(copy=True),
            affected=lambda _result: self.canvas.selected_shapes,
        )
        self.add_label(self.canvas.selected_shape)
        self.shape_selection_changed(True)


    def move_shape(self):
        self._perform_annotation_edit(
            'Move box',
            lambda: self.canvas.end_move(copy=False),
            affected=lambda _result: self.canvas.selected_shapes,
        )


    def toggle_paint_labels_option(self):
        for shape in self.canvas.shapes:
            shape.paint_label = self.display_label_option.isChecked()


    def toggle_draw_square(self):
        self.canvas.set_drawing_shape_to_square(self.draw_squares_option.isChecked())

