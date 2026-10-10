# Changelog

## 2.5.0

- Added dataset-aware YOLO class resolution from nearby `classes.txt` files and dataset-root `data.yaml`, preserving stable class IDs including unused classes.
- Added support for split `images/` and `labels/` trees and relative annotation subdirectories across loading, saving, renaming, deleting, and file-list status indexing.
- Added explicit confirmation for unusually located YOLO class mappings and ambiguity selection when both flat and relative annotation documents exist.
- Added localized, structured diagnostics for missing mappings, out-of-range class IDs, invalid YAML class definitions, and annotation-directory transitions.
- Kept workspace and annotation-directory transitions atomic when class mapping confirmation, document selection, or validation is cancelled or fails.
- Added PyYAML to runtime and frozen-application dependencies, with corresponding third-party notices and regression coverage.

## 2.4.0

- Added persistent image-directory search by file name or relative path, with global `Ctrl+F`, first-result opening, and search-aware filtering and navigation.
- Distinguished label filtering from image search with aligned query fields, concise bilingual descriptions, and dedicated leading filter and search icons.
- Made the always-visible Canvas zoom native-pixel-relative and smoothly cursor-anchored, added a nominal `1%`–`600%` per-image dynamic range, reciprocal 10% wheel/button/keyboard increments, `Ctrl+=`/`Ctrl+-` scaling, `Ctrl+1` actual size, Shift-wheel horizontal navigation, and high-precision wheel support, and hardened fit behavior for tiny, huge, and extreme-aspect images.
- Stabilized the zoom slider while dragging across changing percentage widths, kept outside-image wheel zoom anchored to the pointer, and refreshed pointer coordinates after every wheel zoom.
- Moved coordinates, annotation dimensions, and zoom into a responsive Canvas-local status strip; cleared out-of-image pixel coordinates and derived W/H from the actual constrained rectangle rather than outside pointer displacement, while preserving the view center across status-strip reflows.
- Simplified the Canvas status strip to one grid layout and removed idle W/H labels without moving the zoom slider when annotation dimensions appear or disappear.
- Added a reverse-screen pending-box outline, alignment guides, and subtle interior highlight that remain visible through initial label confirmation.
- Added an optional, persisted View setting to temporarily hide overlapping annotations while drawing and choosing the initial label, restoring their visibility afterward.
- Refined annotation command surfaces and bilingual help, and simplified application structure and drawing presentation ownership.
- Fixed Linux label-color differences between cached and direct Canvas drawing, and made UI regression fixtures independent of platform layout metrics with explicit window cleanup.
- Added one-shot automatic image adjustment and control reset.
- Fixed file-list annotation indicators remaining stale after valid label files were copied into the active annotation directory.
- Made the current-image review shortcuts clear their corresponding state back to Unreviewed when pressed again.

## 2.3.0

- Added a compact lower-left Canvas display-adjustment button with floating workspace-wide and current-image brightness and contrast controls.
- Added session-scoped label color customization and synchronized annotation styling across the Canvas and annotation workflow.
- Replaced the brightness, contrast, and Gamma number fields in Adjust Image with compact sliders, live value badges, and gesture-coalesced Undo.
- Accelerated Canvas and Image-menu adjustments with bounded logical-size previews, a latest-only render queue, decoded-image reuse, adjacent-image prefetch, and cached single-pass lookup tables.
- Refined image-tool previews, geometry controls, colored-frame removal, crop overlays, localization, and command-surface consistency.

## 2.1.0

- Added a complete bilingual keyboard-shortcut catalog and application information dialog with a link to the canonical GitHub repository.
- Added an explicit annotation-format selector with the same pending-edit and storage-transition safeguards as other format changes.
- Added concise near-duplicate and category-conflict indicators with label summaries, focused member inspection, and annotation-list discovery for hidden boxes.
- Added YOLO comment support and corrected Unicode handling for class files.
- Replaced the docked display-adjustment controls with a compact lower-left Canvas button and persistent floating panel for workspace-wide and current-image presentation settings.
- Accelerated Canvas and Image-menu adjustments with bounded logical-size previews, a latest-only render queue, decoded-image reuse, adjacent-image prefetch, and cached single-pass lookup tables.
- Replaced the brightness, contrast, and Gamma number fields in Adjust Image with compact sliders and live value badges, and added one-shot automatic adjustment plus a control reset.
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
