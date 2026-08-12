"""Public contracts for annotation documents and workflows."""

from importlib import import_module

__all__ = (
    "AnnotationBox",
    "AnnotationBoxState",
    "AnnotationDocument",
    "AnnotationDocumentError",
    "AnnotationEditingController",
    "AnnotationFormat",
    "AnnotationHistory",
    "AnnotationSaveCoordinator",
    "AnnotationSnapshot",
    "AnnotationStatus",
    "AnnotationWorkspace",
    "CreateMLRecordIdentity",
    "CreateMLAnnotationCollection",
    "CreateMLCollectionError",
    "CreateMLCollectionFormatError",
    "CreateMLCollectionParseError",
    "CreateMLRecordAmbiguous",
    "MISSING_FINGERPRINT",
    "RenamedAnnotationSessionMigrator",
    "ResourceFingerprint",
    "ReviewStateTransaction",
    "annotation_resources",
    "fingerprint_image",
    "fingerprint_path",
    "save_document",
)

_EXPORT_MODULES = {
    "AnnotationBox": "labelimg.annotations.domain.model",
    "AnnotationBoxState": "labelimg.annotations.domain.history",
    "AnnotationDocument": "labelimg.annotations.domain.model",
    "AnnotationDocumentError": "labelimg.annotations.domain.model",
    "AnnotationEditingController": "labelimg.annotations.application.editing",
    "AnnotationFormat": "labelimg.annotations.domain.model",
    "AnnotationHistory": "labelimg.annotations.domain.history",
    "AnnotationSaveCoordinator": "labelimg.annotations.application.persistence",
    "AnnotationSnapshot": "labelimg.annotations.domain.history",
    "AnnotationStatus": "labelimg.annotations.domain.model",
    "AnnotationWorkspace": "labelimg.annotations.application.workspace",
    "CreateMLRecordIdentity": "labelimg.annotations.infrastructure.formats.create_ml_collection",
    "CreateMLAnnotationCollection": "labelimg.annotations.infrastructure.formats.create_ml_collection",
    "CreateMLCollectionError": "labelimg.annotations.infrastructure.formats.create_ml_collection",
    "CreateMLCollectionFormatError": "labelimg.annotations.infrastructure.formats.create_ml_collection",
    "CreateMLCollectionParseError": "labelimg.annotations.infrastructure.formats.create_ml_collection",
    "CreateMLRecordAmbiguous": "labelimg.annotations.infrastructure.formats.create_ml_collection",
    "MISSING_FINGERPRINT": "labelimg.annotations.infrastructure.storage",
    "RenamedAnnotationSessionMigrator": "labelimg.annotations.application.session",
    "ResourceFingerprint": "labelimg.annotations.infrastructure.storage",
    "ReviewStateTransaction": "labelimg.annotations.application.review",
    "annotation_resources": "labelimg.annotations.application.workspace",
    "fingerprint_image": "labelimg.annotations.infrastructure.storage",
    "fingerprint_path": "labelimg.annotations.infrastructure.storage",
    "save_document": "labelimg.annotations.infrastructure.document",
}


def __getattr__(name):
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
