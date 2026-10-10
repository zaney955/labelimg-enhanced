"""Present annotation diagnostics in the selected application language."""

from html import escape

from labelimg.annotations.domain.model import YoloClassMappingError
from labelimg.localization.runtime import tr


def annotation_error_text(error):
    cause = error
    visited = set()
    while cause is not None and id(cause) not in visited:
        visited.add(id(cause))
        if isinstance(cause, YoloClassMappingError):
            values = {
                "annotation_path": cause.annotation_path,
                "line_number": cause.line_number
                if cause.line_number is not None
                else "—",
            }
            if cause.reason == "missing":
                return tr(
                    "annotation.yoloMissingClasses",
                    **values,
                    checked_paths="\n".join(cause.checked_paths),
                )
            return tr(
                "annotation.yoloClassOutOfRange",
                **values,
                class_index=cause.class_index,
                class_count=cause.class_count,
                max_index=cause.class_count - 1,
                class_list_path=cause.class_list_path,
            )
        cause = cause.__cause__
    return str(error)


def annotation_error_html(error):
    return escape(annotation_error_text(error)).replace("\n", "<br>")
