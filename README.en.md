# LabelImg Enhanced

[简体中文](README.md) | [English](README.en.md)

LabelImg Enhanced is an independently maintained bounding-box annotation tool derived from LabelImg `v1.8.6`. It keeps the familiar `LabelImg` application name and `labelImg` command while improving professional annotation, review, and image-processing workflows.

> This is not an official HumanSignal project.

## Highlights

- Supports Pascal VOC, YOLO, and CreateML with an explicit save-format selector.
- Provides complete Simplified Chinese and English interfaces with instant, persisted switching.
- Supports multi-selection, deterministic overlap targeting, and direct single-box label editing by double-clicking a box or its label text.
- Flags likely duplicate boxes and overlapping category conflicts for focused inspection, editing, visibility changes, deletion, or session-only dismissal.
- Tracks `Unreviewed / Needs Review / Verified` states and filters or sorts files by annotation, review, and save state.
- Provides per-image Undo/Redo, real-time autosave, external-conflict handling, and recoverable file operations.
- Includes rotation, flipping, cropping, resizing, image adjustments, and non-destructive quality checks for corruption, blur, darkness, overexposure, and more.

## Requirements and installation

- Python 3.14
- Windows is the primary supported platform; Linux is verified through headless tests.

Install and launch from the repository root:

```powershell
python -m pip install .
labelImg
```

You can also run `python -m labelimg`. Use the interface to open an image directory, choose an annotation directory, and select the save format.

## Development and validation

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONPATH = "src"
python tools/run_tests.py
python -m pip wheel . --no-deps --no-build-isolation
python tools/run_tests.py --installed
```

The source uses a feature-first modular-monolith structure. See [docs/design](docs/design) for design notes.

## Origin and license

This project is derived from [HumanSignal/labelImg](https://github.com/HumanSignal/labelImg) `v1.8.6` (commit `1ab8241`) and is licensed under the MIT License. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
