"""Canvas rendering, selection, and transient interaction."""

from importlib import import_module

__all__ = (
    "Canvas",
    "CanvasInteraction",
    "CanvasInteractionSnapshot",
    "HoverTarget",
    "SelectionSet",
    "Shape",
)

_EXPORT_MODULES = {
    "Canvas": "labelimg.canvas.widget",
    "CanvasInteraction": "labelimg.canvas.interaction",
    "CanvasInteractionSnapshot": "labelimg.canvas.interaction",
    "HoverTarget": "labelimg.canvas.interaction",
    "SelectionSet": "labelimg.canvas.selection",
    "Shape": "labelimg.canvas.shape",
}


def __getattr__(name):
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
