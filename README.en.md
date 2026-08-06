# LabelImg Enhanced

[简体中文](README.md) | [English](README.en.md)

LabelImg Enhanced is an independently maintained bounding-box annotation tool derived from LabelImg `v1.8.6`. It keeps the original `LabelImg` application name and `labelImg` command while modernizing the Python package structure and maintaining workflow-focused enhancements for professional annotation work.

> This is an independently maintained derivative and is not an official HumanSignal project.

## Highlights

- Complete Simplified Chinese and English interfaces with immediate switching from View → Language and a persisted preference.
- On first launch, `zh-*` system locales use Simplified Chinese; every other locale uses English.
- Annotation boxes use their label color for selected and hovered feedback.
- Ordinary click, Ctrl toggle selection, right-click, and dragging share one deterministic overlap target resolver and never cycle targets.
- Label and file lists provide Windows File Explorer-style multi-selection.
- Independent `Unreviewed / Needs Review / Verified` image review states.
- File filtering and sorting by annotation, review, and persistence state while hidden selections remain retained.
- Per-image Undo/Redo, real-time autosave, external-conflict handling, and recoverable file operations.
- Candidate labels are derived only from saved Pascal VOC, YOLO, or CreateML documents in the current annotation directory.

## Language

View → Language offers “简体中文” and “English”. The current window updates immediately without a restart, and the selection is persisted in LabelImg settings.

Translation covers all application-authored interface text, including menus, toolbars, panels, status messages, guidance, validation errors, confirmations, recovery, and conflict flows. User labels, file names and paths, Pascal VOC/YOLO/CreateML format names, and verbatim operating-system diagnostics remain unchanged.

## Environment

- Python 3.14
- PyQt5 5.15
- lxml 6
- Windows is the primary supported platform; Linux is verified through headless tests.

## Installation

Install from source:

```powershell
python -m pip install .
labelImg
```

The module entry point is also available:

```powershell
python -m labelimg
```

## Development and validation

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONPATH = "src"
python tools/run_tests.py
python -m pip wheel . --no-deps --no-build-isolation
python tools/run_tests.py --installed
```

The bilingual catalogs use stable message IDs. Tests require identical English and Chinese keys and formatting parameters, and prevent UI code from reintroducing hard-coded application text. See [Bilingual Interface Design](docs/design/bilingual-interface.md).

## Origin and license

This project is based on [HumanSignal/labelImg](https://github.com/HumanSignal/labelImg) `v1.8.6` (commit `1ab8241`), retains the complete upstream Git history, and uses the MIT License. See [NOTICE.md](NOTICE.md) for provenance details.
