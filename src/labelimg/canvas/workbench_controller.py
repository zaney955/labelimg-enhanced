"""CanvasActionsMixin extracted from the top-level workbench window."""

#!/usr/bin/env python
# -*- coding: utf-8 -*-


import math

from PyQt5.QtCore import QPoint, QPointF, QTimer, Qt

import labelimg.ui.generated_resources  # noqa: F401 - registers Qt resources
from labelimg.ui.actions import set_action_copy
from labelimg.localization.runtime import tr
from labelimg.canvas.widget import Canvas


class CanvasActionsMixin:
    ZOOM_FACTOR = 1.10
    NOMINAL_MIN_ZOOM = 1.0
    NOMINAL_MAX_ZOOM = 600.0
    MAX_WIDGET_DIMENSION = 16777215.0

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


    def scroll_request(self, delta, orientation, pixel_delta=False):
        bar = self.scroll_bars[orientation]
        movement = (
            -float(delta)
            if pixel_delta
            else -float(delta) / 120.0 * bar.singleStep()
        )
        bar.setValue(int(round(bar.value() + movement)))


    def pan_request(self, delta_x, delta_y):
        horizontal = self.scroll_bars[Qt.Horizontal]
        vertical = self.scroll_bars[Qt.Vertical]
        view_offset = self.canvas.view_offset
        if horizontal.maximum():
            horizontal.setValue(horizontal.value() - delta_x)
        else:
            view_offset.setX(view_offset.x() + delta_x)
        if vertical.maximum():
            vertical.setValue(vertical.value() - delta_y)
        else:
            view_offset.setY(view_offset.y() + delta_y)
        self.canvas.set_view_offset(view_offset)
        self.queue_canvas_readout_refresh()


    def queue_canvas_readout_refresh(self, _value=None):
        # Scrollbar signals precede QScrollArea's final Canvas positioning.
        QTimer.singleShot(0, self.canvas.refresh_tracked_pointer_coordinates)


    def set_zoom(self, value):
        self.actions.fitWidth.setChecked(False)
        self.actions.fitWindow.setChecked(False)
        self.zoom_mode = self.MANUAL_ZOOM
        self._set_zoom_value(float(value))


    def add_zoom(self, units=1.0):
        current = self.zoom_widget.value()
        target = current * math.pow(self.ZOOM_FACTOR, float(units))
        if (
            (current < 100.0 < target)
            or (current > 100.0 > target)
        ):
            target = 100.0
        self.set_zoom(target)


    def zoom_request(self, units, canvas_position):
        anchor = self._capture_zoom_anchor(canvas_position)
        current = self.zoom_widget.value()
        target = current * math.pow(self.ZOOM_FACTOR, float(units))
        if (
            (current < 100.0 < target)
            or (current > 100.0 > target)
        ):
            target = 100.0
        self.actions.fitWidth.setChecked(False)
        self.actions.fitWindow.setChecked(False)
        self.zoom_mode = self.MANUAL_ZOOM
        self._set_zoom_value(target, anchor=anchor)
        if anchor is not None:
            viewport_position = anchor[1]
            canvas_point = self.canvas.mapFrom(
                self.scroll_area.viewport(),
                QPoint(
                    round(viewport_position.x()),
                    round(viewport_position.y()),
                ),
            )
            self.canvas.refresh_pointer_coordinates(canvas_point)


    def _set_zoom_value(self, value, anchor=None, recenter=False):
        self._pending_zoom_anchor = anchor
        self._pending_zoom_recenter = bool(recenter)
        changed = self.zoom_widget.setValue(value)
        if not changed:
            if recenter and not self.image.isNull():
                self.apply_zoom_value(self.zoom_widget.value())
            else:
                self._pending_zoom_anchor = None
                self._pending_zoom_recenter = False


    def apply_zoom_value(self, value):
        if self.image.isNull():
            return
        anchor = getattr(self, "_pending_zoom_anchor", None)
        recenter = bool(getattr(self, "_pending_zoom_recenter", False))
        self._pending_zoom_anchor = None
        self._pending_zoom_recenter = False
        if anchor is None and not recenter and self.zoom_mode != self.MANUAL_ZOOM:
            self.zoom_mode = self.MANUAL_ZOOM
            self.actions.fitWidth.setChecked(False)
            self.actions.fitWindow.setChecked(False)
        if anchor is None and not recenter:
            anchor = self._capture_zoom_anchor()
        self._ignore_zoom_viewport_resize = True
        self.canvas.reset_view_geometry()
        self._render_canvas_scale(value)
        if recenter:
            for bar in self.scroll_bars.values():
                bar.setValue(0)
        elif anchor is not None:
            self._restore_zoom_anchor(*anchor)
        self._update_fit_width_availability()
        QTimer.singleShot(0, self._finish_zoom_geometry_change)


    def _finish_zoom_geometry_change(self):
        self._ignore_zoom_viewport_resize = False
        self.canvas.refresh_tracked_pointer_coordinates()


    def _render_canvas_scale(self, value):
        self.canvas.scale = 0.01 * float(value)
        self.canvas.label_font_size = int(
            0.02 * max(self.image.width(), self.image.height())
        )
        self.canvas.adjustSize()
        self.canvas.update()


    def _capture_zoom_anchor(self, canvas_position=None):
        if self.canvas.pixmap is None or self.canvas.pixmap_size.isEmpty():
            return None
        viewport = self.scroll_area.viewport()
        canvas_origin = self.canvas.mapTo(viewport, QPoint(0, 0))
        if canvas_position is None:
            viewport_point = QPointF(viewport.rect().center())
            widget_point = QPointF(
                self.canvas.mapFrom(
                    viewport,
                    viewport.rect().center(),
                )
            )
        else:
            widget_point = QPointF(canvas_position)
            viewport_point = QPointF(canvas_origin) + widget_point
        image_point = self.canvas.transform_pos(widget_point)
        size = self.canvas.pixmap_size
        image_point.setX(min(max(image_point.x(), 0.0), float(size.width())))
        image_point.setY(min(max(image_point.y(), 0.0), float(size.height())))
        return image_point, viewport_point


    def _restore_zoom_anchor(self, image_point, viewport_point):
        target_widget = self.canvas.image_to_widget(image_point)
        h_bar = self.scroll_bars[Qt.Horizontal]
        v_bar = self.scroll_bars[Qt.Vertical]
        h_bar.setValue(int(round(target_widget.x() - viewport_point.x())))
        v_bar.setValue(int(round(target_widget.y() - viewport_point.y())))
        viewport = self.scroll_area.viewport()
        canvas_origin = self.canvas.mapTo(viewport, QPoint(0, 0))
        current_viewport = QPointF(canvas_origin) + self.canvas.image_to_widget(
            image_point
        )
        residual = QPointF(viewport_point) - current_viewport
        viewport_size = viewport.size()
        image_size = self.canvas.pixmap_size
        scaled_width = image_size.width() * self.canvas.scale
        scaled_height = image_size.height() * self.canvas.scale
        left = top = right = bottom = 0.0
        if scaled_width >= viewport_size.width():
            if residual.x() > 0:
                left = residual.x()
            elif residual.x() < 0:
                right = -residual.x()
        if scaled_height >= viewport_size.height():
            if residual.y() > 0:
                top = residual.y()
            elif residual.y() < 0:
                bottom = -residual.y()
        if any((left, top, right, bottom)):
            self.canvas.set_content_margins(left, top, right, bottom)
            self.canvas.adjustSize()
            target_widget = self.canvas.image_to_widget(image_point)
            h_bar.setValue(int(round(
                target_widget.x() - viewport_point.x()
            )))
            v_bar.setValue(int(round(
                target_widget.y() - viewport_point.y()
            )))
            canvas_origin = self.canvas.mapTo(viewport, QPoint(0, 0))
            current_viewport = (
                QPointF(canvas_origin)
                + self.canvas.image_to_widget(image_point)
            )
            residual = QPointF(viewport_point) - current_viewport
        if not residual.isNull():
            self.canvas.set_view_offset(self.canvas.view_offset + residual)


    def set_fit_window(self, value=True):
        if not value:
            self.actions.fitWindow.setChecked(True)
            return
        self.actions.fitWidth.setChecked(False)
        self.zoom_mode = self.FIT_WINDOW
        self.adjust_scale(recenter=True)


    def set_fit_width(self, value=True):
        if not value:
            self.actions.fitWidth.setChecked(True)
            return
        if not self._fit_width_available():
            self.actions.fitWidth.setChecked(False)
            return
        self.actions.fitWindow.setChecked(False)
        self.zoom_mode = self.FIT_WIDTH
        self.adjust_scale(recenter=True)


    def toggle_polygons(self, value):
        self.label_visibility_requested(tuple(self.canvas.shapes), value)


    def toggle_all_annotations(self, visible):
        """Apply one explicit all-visible state from the annotation header."""
        self.toggle_polygons(bool(visible))
        self.sync_all_annotations_action(visible)


    def sync_all_annotations_action(self, visible):
        """Retranslate the all-visible projection without changing shapes."""
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


    def canvas_viewport_resize_event(self, event):
        if (
            not self.canvas
            or self.image is None
            or self.image.isNull()
            or event.oldSize().isEmpty()
            or bool(getattr(self, "_ignore_zoom_viewport_resize", False))
        ):
            return
        if self.zoom_mode != self.MANUAL_ZOOM:
            if not hasattr(self, "_fit_resize_timer"):
                self._fit_resize_timer = QTimer(self)
                self._fit_resize_timer.setSingleShot(True)
                self._fit_resize_timer.timeout.connect(
                    self._refit_after_viewport_resize
                )
            self._fit_resize_timer.start(0)
            return
        if getattr(self, "_pending_manual_resize_anchor", None) is not None:
            return
        old_center = QPoint(
            max(0, (event.oldSize().width() - 1) // 2),
            max(0, (event.oldSize().height() - 1) // 2),
        )
        canvas_point = self.canvas.mapFrom(
            self.scroll_area.viewport(),
            old_center,
        )
        captured = self._capture_zoom_anchor(QPointF(canvas_point))
        if captured is not None:
            # A footer reflow and a window/dock resize can arrive together.
            # Retain the center before the first resize, not an interim layout.
            self._pending_manual_resize_anchor = captured[0]
            QTimer.singleShot(0, self._finish_manual_viewport_resize)


    def _finish_manual_viewport_resize(self):
        image_point = self._pending_manual_resize_anchor
        self._pending_manual_resize_anchor = None
        if self.zoom_mode == self.MANUAL_ZOOM and image_point is not None:
            self._restore_manual_resize_anchor(image_point)


    def _refit_after_viewport_resize(self):
        if not self.image.isNull() and self.zoom_mode != self.MANUAL_ZOOM:
            self.adjust_scale(recenter=True)


    def _restore_manual_resize_anchor(self, image_point):
        if self.image.isNull():
            return
        self._update_zoom_range(retain_current=True)
        viewport_center = QPointF(self.scroll_area.viewport().rect().center())
        self.canvas.reset_view_geometry()
        self._restore_zoom_anchor(image_point, viewport_center)
        self.queue_canvas_readout_refresh()


    def paint_canvas(self):
        assert not self.image.isNull(), "cannot paint null image"
        self._render_canvas_scale(self.zoom_widget.value())


    def adjust_scale(self, initial=False, recenter=False):
        mode = self.FIT_WINDOW if initial else self.zoom_mode
        if initial:
            self.zoom_mode = self.FIT_WINDOW
            self.actions.fitWindow.setChecked(True)
            self.actions.fitWidth.setChecked(False)
        if mode == self.FIT_WIDTH and not self._fit_width_available():
            self.zoom_mode = self.MANUAL_ZOOM
            self.actions.fitWidth.setChecked(False)
            self._update_zoom_range(retain_current=True)
            return
        self._update_zoom_range(
            retain_current=mode == self.MANUAL_ZOOM and not initial,
        )
        value = 100.0 * self.scalers[mode]()
        if mode == self.FIT_WINDOW:
            value = min(100.0, value)
        self._set_zoom_value(value, recenter=recenter or initial)
        self._update_fit_width_availability()


    def scale_fit_window(self):
        """Figure out the size of the pixmap in order to fit the main widget."""
        viewport_size = self.scroll_area.maximumViewportSize()
        w1 = max(1.0, float(viewport_size.width()))
        h1 = max(1.0, float(viewport_size.height()))
        a1 = w1 / h1
        # Calculate a new scale value based on the pixmap's aspect ratio.
        image_size = self.canvas.pixmap_size
        w2 = image_size.width() - 0.0
        h2 = image_size.height() - 0.0
        a2 = w2 / h2
        return min(1.0, w1 / w2 if a2 >= a1 else h1 / h2)


    def scale_fit_width(self):
        w = max(
            1.0,
            float(self.scroll_area.maximumViewportSize().width()),
        )
        return w / self.canvas.pixmap_size.width()


    def _fit_width_available(self):
        if self.canvas.pixmap_size.isEmpty():
            return False
        return (
            100.0 * self.scale_fit_width()
            <= self._safe_max_zoom() + 1e-9
        )


    def _safe_max_zoom(self):
        image_size = self.canvas.pixmap_size
        if image_size.isEmpty():
            return self.NOMINAL_MAX_ZOOM
        largest_dimension = max(
            float(image_size.width()),
            float(image_size.height()),
        )
        return 100.0 * self.MAX_WIDGET_DIMENSION / largest_dimension


    def _zoom_range(self, retain_current=False):
        fit_window = 100.0 * self.scale_fit_window()
        fit_width = 100.0 * self.scale_fit_width()
        safe_maximum = self._safe_max_zoom()
        minimum = min(self.NOMINAL_MIN_ZOOM, fit_window)
        maximum = min(self.NOMINAL_MAX_ZOOM, safe_maximum)
        if fit_width <= safe_maximum + 1e-9:
            maximum = max(maximum, fit_width)
        if retain_current:
            maximum = max(
                maximum,
                min(self.zoom_widget.value(), safe_maximum),
            )
        return minimum, max(minimum, maximum)


    def _update_zoom_range(self, retain_current=False):
        if self.canvas.pixmap_size.isEmpty():
            self.zoom_widget.setRangeValues(
                self.NOMINAL_MIN_ZOOM,
                self.NOMINAL_MAX_ZOOM,
            )
        else:
            self.zoom_widget.setRangeValues(
                *self._zoom_range(retain_current=retain_current)
            )
        self._update_fit_width_availability()


    def _update_fit_width_availability(self):
        if not hasattr(self, "actions") or not hasattr(self.actions, "fitWidth"):
            return
        available = bool(self.file_path) and self._fit_width_available()
        self.actions.fitWidth.setEnabled(available)
        if not available:
            self.actions.fitWidth.setChecked(False)


    def delete_selected_shape(self):
        self.delete_annotation_shapes(
            tuple(self.canvas.selected_shapes),
            'Delete boxes',
        )
    def toggle_paint_labels_option(self):
        for shape in self.canvas.shapes:
            shape.paint_label = self.display_label_option.isChecked()


    def toggle_draw_square(self):
        self.canvas.set_drawing_shape_to_square(self.draw_squares_option.isChecked())

