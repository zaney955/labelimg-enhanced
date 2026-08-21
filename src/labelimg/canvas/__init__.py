"""Canvas rendering, selection, and transient interaction."""

from importlib import import_module

__all__ = (
    "Canvas",
    "CanvasInteraction",
    "CanvasInteractionSnapshot",
    "CATEGORY_CONFLICT",
    "DUPLICATE_LABEL_RISK",
    "HoverTarget",
    "NearDuplicateCluster",
    "SelectionSet",
    "Shape",
    "cluster_bounds",
    "detect_near_duplicate_clusters",
)

_EXPORT_MODULES = {
    "Canvas": "labelimg.canvas.widget",
    "CanvasInteraction": "labelimg.canvas.interaction",
    "CanvasInteractionSnapshot": "labelimg.canvas.interaction",
    "CATEGORY_CONFLICT": "labelimg.canvas.near_duplicates",
    "DUPLICATE_LABEL_RISK": "labelimg.canvas.near_duplicates",
    "HoverTarget": "labelimg.canvas.interaction",
    "NearDuplicateCluster": "labelimg.canvas.near_duplicates",
    "SelectionSet": "labelimg.canvas.selection",
    "Shape": "labelimg.canvas.shape",
    "cluster_bounds": "labelimg.canvas.near_duplicates",
    "detect_near_duplicate_clusters": "labelimg.canvas.near_duplicates",
}


def __getattr__(name):
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
