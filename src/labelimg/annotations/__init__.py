"""Public contracts for annotation documents and workflows."""

from importlib import import_module

__all__ = (
    "AnnotationBox",
    "AnnotationDocument",
    "AnnotationDocumentError",
    "AnnotationEditingController",
    "AnnotationFormat",
    "AnnotationHistory",
    "AnnotationSaveCoordinator",
    "AnnotationSnapshot",
    "AnnotationStatus",
    "AnnotationWorkspace",
    "ReviewStateTransaction",
)

_EXPORT_MODULES = {
    "AnnotationBox": "labelimg.annotations.domain.model",
    "AnnotationDocument": "labelimg.annotations.domain.model",
    "AnnotationDocumentError": "labelimg.annotations.domain.model",
    "AnnotationEditingController": "labelimg.annotations.application.editing",
    "AnnotationFormat": "labelimg.annotations.domain.model",
    "AnnotationHistory": "labelimg.annotations.domain.history",
    "AnnotationSaveCoordinator": "labelimg.annotations.application.persistence",
    "AnnotationSnapshot": "labelimg.annotations.domain.history",
    "AnnotationStatus": "labelimg.annotations.domain.model",
    "AnnotationWorkspace": "labelimg.annotations.application.workspace",
    "ReviewStateTransaction": "labelimg.annotations.application.review",
}


def __getattr__(name):
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
