# Changelog

## 2.1.0

- Added a complete bilingual keyboard-shortcut catalog and application information dialog with a link to the canonical GitHub repository.
- Added an explicit annotation-format selector with the same pending-edit and storage-transition safeguards as other format changes.
- Added concise near-duplicate and category-conflict indicators with label summaries, focused member inspection, and annotation-list discovery for hidden boxes.
- Added YOLO comment support and corrected Unicode handling for class files.
- Made queued automatic saves finish safely before image navigation.
- Kept batch deletion responsive for very high-resolution images by releasing old pixel buffers, decoding the replacement image in the background, and safely joining image-loading threads during shutdown.
- Removed obsolete upstream-era project files and standardized review shortcuts.

## 2.0.0

- Reorganized the source as a feature-first modular monolith with explicit `annotations`, `canvas`, `files`, `image_tools`, `localization`, `platform`, `ui`, and `workbench` ownership.
- Replaced the flat internal module layout without compatibility shims; `labelimg.app` is intentionally removed.
- Moved the `labelImg` and `python -m labelimg` composition entry to `labelimg.workbench.bootstrap`.
- Introduced Qt-free annotation domain models and workbench session state, with Qt projection isolated in feature UI adapters.
- Added AST architecture tests for dependency direction, legacy paths, root-package hygiene, wildcard imports, and image-library ownership.
- Mirrored the production feature packages in the test tree while retaining isolated-per-file Qt execution.

## 1.9.0

- Added complete Simplified Chinese and English application interfaces with an immediate, persisted View → Language switch and system-locale first-launch mapping.
- Added strict bilingual catalog, format-field, runtime-switch, and hard-coded UI text regression coverage.

- Added synchronized canvas and label-list multi-selection.
- Added Ctrl drag-region selection and deterministic overlap targeting.
- Applied label-colored selected outlines and translucent fills.
- Scoped copy, paste, duplication, and deletion to selected annotations.
- Added the adaptive five-column candidate-label dialog.
- Migrated the implementation from top-level `libs` modules to `src/labelimg`.
- Replaced legacy `setup.py` packaging with `pyproject.toml`.
- Added Python 3.14 Windows and Linux validation.
