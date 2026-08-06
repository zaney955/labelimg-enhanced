# Changelog

## 1.9.0

- Added complete Simplified Chinese and English application interfaces with an immediate, persisted View → Language switch and system-locale first-launch mapping.
- Added strict bilingual catalog, format-field, runtime-switch, and hard-coded UI text regression coverage.

- Added synchronized canvas and label-list multi-selection.
- Added Ctrl drag-region selection and overlap cycling.
- Applied label-colored selected outlines and translucent fills.
- Scoped copy, paste, duplication, and deletion to selected annotations.
- Added the adaptive five-column candidate-label dialog.
- Migrated the implementation from top-level `libs` modules to `src/labelimg`.
- Replaced legacy `setup.py` packaging with `pyproject.toml`.
- Added Python 3.14 Windows and Linux validation.
