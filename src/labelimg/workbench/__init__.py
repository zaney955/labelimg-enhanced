"""Top-level application composition and workbench UI."""

from importlib import import_module

__all__ = (
    "WorkbenchLaunchOptions",
    "WorkbenchSession",
    "create_workbench",
)

_EXPORT_MODULES = {
    "WorkbenchLaunchOptions": "labelimg.workbench.bootstrap",
    "WorkbenchSession": "labelimg.workbench.session",
    "create_workbench": "labelimg.workbench.bootstrap",
}


def __getattr__(name):
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
