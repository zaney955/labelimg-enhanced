# LabelImg Enhanced

[简体中文](README.md) | [English](README.en.md)

LabelImg Enhanced is an independently maintained bounding-box annotation tool derived from LabelImg `v1.8.6`. It keeps the familiar `LabelImg` application name and `labelImg` command while improving professional annotation, review, and image-processing workflows.

> This is not an official HumanSignal project.

## Highlights

- Supports Pascal VOC, YOLO, and CreateML with an explicit save-format selector.
- Provides complete Simplified Chinese and English interfaces with instant, persisted switching.
- [A consistent modern interface](docs/design/ui-presentation.md), with rules beside batch previews, image previews beside settings, and clear layouts for statistics, cleanup, recovery and dialogs.
- Supports multi-selection, deterministic overlap targeting, and direct single-box label editing by double-clicking a box or its label text.
- Flags likely duplicate boxes and overlapping category conflicts for focused inspection, editing, visibility changes, deletion, or session-only dismissal.
- Searches the current image directory live by file name or relative path, and tracks `Unreviewed / Needs Review / Verified` states with annotation, review, and save-state filtering or sorting.
- Use the filter button beside image search to search and check one or more annotation categories, then choose Include All Selected Categories or Include Any Selected Category. XML, YOLO, and CreateML categories combine with filename and state filters; click the category summary to edit it or clear it independently. Previous/Next follows the filtered images.
- Provides per-image Undo/Redo, real-time autosave, external-conflict handling, and recoverable file operations.
- Tools → Clean Annotation Files previews unmatched or empty annotation files, offers category and per-file selection, and moves selected files to the Recycle Bin with recovery under File → Recent File Operations. Empty annotations are unchecked by default to preserve intentional negative samples.
- Tools → Annotation Statistics charts category box counts and distinct-image counts, with a numeric details/share table, category filtering, and refresh. It covers the entire workspace and identifies unsaved edits, empty/missing annotations, and skipped images.
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

The file panel shows the current annotation's actual save target, with the complete path on hover. Existing documents are updated in place; new documents preserve relative subdirectories. When a standalone image has no known mapping to a separate annotation directory, choose its destination with `Ctrl+S` before autosave writes anything. Cancelling keeps edits unsaved. Converting into an existing destination also requires explicit selection.

The file panel shows the current annotation's actual save target, with the complete path on hover. Existing documents are updated in place; new documents preserve relative subdirectories. When a standalone image has no known mapping to a separate annotation directory, choose its destination with `Ctrl+S` before autosave writes anything. Cancelling keeps edits unsaved. Converting into an existing destination also requires explicit selection.

For split YOLO datasets, select `images` as the image directory and `labels` as the annotation directory. Relative paths match `images/train/a.jpg` to `labels/train/a.txt`, with support for flat annotation directories. When both locations contain annotations, choose the active document. Class names come from the annotation directory's `classes.txt`, then the `labels` root's `classes.txt`, then `names` in the dataset root's `data.yaml`. Missing or empty mappings fall back to other ancestor locations within that dataset only. Non-recommended locations require confirmation showing the configuration path and ordered class IDs before use in the workspace. Cancelling preserves current annotations; changed configuration content requires confirmation again. Saving preserves all existing class IDs and appends new classes.

YOLO saves maintain a shared `classes.txt` at the workspace annotation root (the `labels` root in a conventional dataset) alongside the current subdirectory's mapping. Existing mappings must be compatible prefixes of one class-ID order. Conflicting definitions identify both configurations and stop saving instead of silently renumbering annotations. The TXT and mappings commit together with rollback on failure; existing `data.yaml` files remain read-only.

YOLO saves maintain a shared `classes.txt` at the workspace annotation root (the `labels` root in a conventional dataset) alongside the current subdirectory's mapping. Existing mappings must be compatible prefixes of one class-ID order. Conflicting definitions identify both configurations and stop saving instead of silently renumbering annotations. The TXT and mappings commit together with rollback on failure; existing `data.yaml` files remain read-only.

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

The source uses a feature-first modular-monolith structure. See the [documentation index](docs/README.md) for terminology, current designs, and decisions.

## Origin and license

This project is derived from [HumanSignal/labelImg](https://github.com/HumanSignal/labelImg) `v1.8.6` (commit `1ab8241`) and is licensed under the MIT License. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
