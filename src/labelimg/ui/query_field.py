"""Shared presentation for text fields that narrow list content."""

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QLineEdit


def decorate_list_query_field(field, icon_alias):
    """Apply the shared, non-interactive leading-icon query-field treatment."""
    icon_action = field.addAction(
        QIcon(":/" + icon_alias),
        QLineEdit.LeadingPosition,
    )
    icon_action.setEnabled(False)
    field.setClearButtonEnabled(True)
    return icon_action
