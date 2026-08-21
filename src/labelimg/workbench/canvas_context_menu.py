"""Target-scoped Canvas context command menus."""

from PyQt5.QtWidgets import QMenu

from labelimg.localization.runtime import tr
from labelimg.ui.actions import new_icon


class CanvasContextMenuController:
    """Build transient menus from the Canvas selection context."""

    def __init__(
        self,
        canvas,
        *,
        draw_action,
        edit_action,
        copy_action,
        duplicate_action,
        paste_action,
        delete_action,
        clipboard_count,
        set_selection_visible,
    ):
        self.canvas = canvas
        self.draw_action = draw_action
        self.edit_action = edit_action
        self.copy_action = copy_action
        self.duplicate_action = duplicate_action
        self.paste_action = paste_action
        self.delete_action = delete_action
        self.clipboard_count = clipboard_count
        self.set_selection_visible = set_selection_visible

    def build(self, kind):
        menu = QMenu(self.canvas)
        if kind == "blank":
            self._add_source_action(
                menu,
                self.draw_action,
                tr("crtBox"),
            )
            count = int(self.clipboard_count())
            if count:
                self._add_source_action(
                    menu,
                    self.paste_action,
                    self._count_text("paste", count),
                )
            return menu

        selected = tuple(self.canvas.selected_shapes)
        count = len(selected)
        if kind not in ("single", "multiple") or not count:
            return menu

        if kind == "single" and count == 1:
            edit = self._add_source_action(
                menu,
                self.edit_action,
                tr("canvasMenu.edit"),
            )
            menu.setDefaultAction(edit)

        self._add_source_action(
            menu,
            self.copy_action,
            self._count_text("copy", count),
        )
        self._add_source_action(
            menu,
            self.duplicate_action,
            self._count_text("duplicate", count),
        )

        all_visible = all(
            self.canvas.isVisible(shape) for shape in selected
        )
        visible = not all_visible
        visibility = menu.addAction(
            new_icon("visibility"),
            self._count_text("hide" if all_visible else "show", count),
        )
        visibility.triggered.connect(
            lambda _checked=False, shapes=selected, value=visible:
            self.set_selection_visible(shapes, value)
        )

        menu.addSeparator()
        self._add_source_action(
            menu,
            self.delete_action,
            self._count_text("delete", count),
        )
        return menu

    def show(self, request):
        menu = self.build(request.kind)
        try:
            if menu.actions():
                menu.exec_(request.global_position)
        finally:
            menu.deleteLater()

    @staticmethod
    def _count_text(command, count):
        suffix = "One" if count == 1 else "Many"
        return tr(
            "canvasMenu.%s%s" % (command, suffix),
            count=count,
        )

    @staticmethod
    def _add_source_action(menu, source, text):
        command = menu.addAction(source.icon(), text)
        command.setEnabled(source.isEnabled())
        command.triggered.connect(
            lambda _checked=False, action=source: action.trigger()
        )
        return command


__all__ = ("CanvasContextMenuController",)
