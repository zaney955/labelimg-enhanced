# LabelImg Enhanced

[简体中文](README.md) | [English](README.en.md)

LabelImg Enhanced is an independently maintained bounding-box annotation tool derived from LabelImg `v1.8.6`. It keeps the familiar `LabelImg` application name and `labelImg` command while improving professional annotation, review, and image-processing workflows.

> This is not an official HumanSignal project.

## Highlights

- Supports Pascal VOC, YOLO, and CreateML with an explicit save-format selector.
- Provides complete Simplified Chinese and English interfaces with instant, persisted switching.
- Supports multi-selection, deterministic overlap targeting, and direct single-box label editing by double-clicking a box or its label text.
- Flags likely duplicate boxes and overlapping category conflicts for focused inspection, editing, visibility changes, deletion, or session-only dismissal.
- Searches the current image directory live by file name or relative path, and tracks `Unreviewed / Needs Review / Verified` states with annotation, review, and save-state filtering or sorting.
- Provides per-image Undo/Redo, real-time autosave, external-conflict handling, and recoverable file operations.
- Includes rotation, flipping, cropping, native-pixel-relative zoom, and image adjustments; a dedicated strip below the Canvas shows in-image pixel coordinates and actual annotation dimensions on the left and a nominal `1%–600%` zoom slider on the right, safely expanding for exact fit scales and wrapping when space is limited. `Ctrl+=`/`Ctrl+-` apply reciprocal 10% increments, `Ctrl+1` restores actual size, Ctrl-wheel zooms around the pointer, Shift-wheel moves horizontally, and non-destructive quality checks find corruption, blur, darkness, overexposure, and more.

## Requirements and installation

- Python 3.14
- Windows is the primary supported platform; Linux is verified through headless tests.

Install and launch from the repository root:

```powershell
python -m pip install .
labelImg
```

You can also run `python -m labelimg`. Use the interface to open an image directory, choose an annotation directory, and select the save format.

## Updates

By default, the application checks asynchronously for the latest stable release after launch, at most once every 24 hours. Disable this under Settings → Automatically Check for Updates, or check immediately with Help → Check for Updates. Python environments can copy an upgrade command, managed Windows installations can explicitly download and verify an update installer, and portable builds can only open the Release. The application never runs `pip`, installs silently, or bypasses unsaved-work guards.

Maintainers trigger the release workflow with an annotated tag that exactly matches `src/labelimg/__init__.py` (for example, `v2.1.0`). CI validates the version on Windows, runs tests, builds the wheel, PyInstaller onedir bundle, and current-user Inno Setup EXE, then generates a SHA-256 manifest and provenance attestation before creating a draft GitHub Release. The installer is currently unsigned and therefore produces an unknown-publisher warning; SHA-256 verifies integrity relative to the Release manifest, not publisher identity.

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
