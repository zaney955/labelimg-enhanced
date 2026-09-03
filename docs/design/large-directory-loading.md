# Large-directory loading

Status: implemented. The benchmark below records the implementation measurement in the `DL` environment; it is not a fresh measurement of every checkout.

## Outcome

Opening an image directory or changing its annotation directory becomes usable at **directory ready state**, before **workspace index completion**. The normal workload is 10,000 local images with annotations; 50,000 images must still support responsive navigation, cancellation, editing, and visible-list interaction, without a fixed completion-time promise.

The index exists only in memory for the current application session. [ADR 0024](../adr/0024-open-large-directories-progressively-with-session-only-indexes.md) records this decision; [ADR 0025](../adr/0025-synchronize-only-the-current-annotation-document.md) limits external document synchronization.

## User-visible semantics

### Directory ready state

A new workspace commits only when it can atomically install the image and annotation directories, stable naturally ordered discovered-file list, loadable current image and annotation document, and authoritative save target. Until then, the previous workspace remains intact.

Editing, saving, name search, and navigation become available at this point. Navigating to a file whose annotation state is not indexed prioritizes its exact annotation load; placeholder state is never editable.

### Workspace index completion

Annotation, review, ambiguity, and persistence states arrive progressively. Badges may update, but rows do not move as results arrive. State-dependent controls remain disabled with visible indexing progress until their required data is complete; incomplete sorting or filtering results are never presented as authoritative.

Image-quality content validation is a separate explicit operation. Opening a directory may bulk-load quality-cache summaries but does not hash every image.

### Progress, cancellation, and errors

Progress is non-modal, for example `Discovered X · Indexed Y`. Each load has a monotonically increasing generation identity. Selecting another directory immediately invalidates the prior generation; late results are discarded. Explicit stop leaves an already-ready workspace usable with an incomplete index and offers resume.

A corrupt or disappearing non-current file contributes to an aggregated warning without aborting the load. If the proposed current image cannot load, the coordinator tries the next usable image. Repeated errors do not open one modal dialog per file.

Application-owned file operations update the index immediately. Debounced metadata differences in the watched annotation directory update only affected image statuses and candidate-label contributions. Other external changes appear through refresh, reopening, or access to the affected file; directory events never trigger a full synchronous rescan.

Refresh preserves current image, selection, filters, Canvas view, history, and unsaved edits. A dirty current document is not replaced; its external changes use the [synchronization and conflict contract](undo-redo-and-file-recovery.md#external-conflicts).

## Architecture

| Owner | Responsibility |
| --- | --- |
| [files.application.discovery](../../src/labelimg/files/application/discovery.py) | Qt-free recursive image discovery and portable natural-sort keys. |
| [annotations.application.workspace](../../src/labelimg/annotations/application/workspace.py) | Resource indexing and immutable per-image snapshots. |
| [workbench](../../src/labelimg/workbench/main_window.py) | Atomic workspace transition and authoritative active document. |
| [files.ui.loading](../../src/labelimg/files/ui/loading.py) | Workers, generations, progress, stop/resume, and bounded publication. |
| [files.ui.list_widget](../../src/labelimg/files/ui/list_widget.py) | Virtualized `QAbstractListModel` and proxy filtering/sorting. |

Workers discover and sort paths, then build remaining annotation snapshots without mutating the active workspace. The UI thread checks the generation and applies results through their authoritative owner. Application and domain modules neither import Qt nor expose Qt thread types.

One per-image snapshot supplies document choices, active choice, annotation/review state, ambiguity/persistence flags, candidate-label contribution, and resource fingerprints. File-list population consumes this bulk state instead of independently querying each property.

The index avoids repeated work:

- Compute each relative natural-sort key once, sort discovery once, and reuse the default-name order. Read image modification times only when the chosen sort requires them.
- Read each physical annotation resource once per build; parse, hash, and retain recovery bytes from that byte sequence. Deduplicate shared YOLO vocabularies.
- Use path-to-snapshot and path-to-row dictionaries. Build CreateML exact-reference and legacy-basename indexes once; resolution and candidate aggregation do not scan every collection record for each image.
- Load quality-cache summaries once without full-image hashing. A startup directory follows one import transition.
- Publish stable file order, then bounded immutable state batches. The virtualized list preserves selection, range selection, context menus, keyboard navigation, drag behavior, and file-operation semantics.

## Performance budget and recorded measurement

The opt-in [benchmark](../../tools/benchmark_directory_loading.py) uses the real `MainWindow.import_dir_images()` and `MainWindow._switch_annotation_directory()` entry points. The recorded run used `DL` Conda, Python 3.14.2, and small local PNG/Pascal VOC fixtures; fixture creation was excluded.

| 10,000-file measurement | Recorded result | Target |
| --- | ---: | ---: |
| Directory ready state | 0.214 s | < 0.500 s |
| Workspace index completion | 3.853 s | < 5.000 s |
| Longest measured UI publication batch | 0.039 s | <= 0.050 s |
| Synchronous image-directory compatibility path | 1.747 s | Report only |
| Synchronous annotation-directory compatibility path | 3.366 s | Report only |

Publication uses 64-row batches. The responsiveness contract is broader than the measured batch: no uninterrupted UI-thread task may exceed 50 ms, and the interface remains interactive throughout indexing. Discovery, annotation resolution, status lookup, and row lookup must have no quadratic call-count growth.

Wall-clock budgets are measured in `DL` separately from correctness tests. CI uses deterministic resource-read counts, bounded growth, generation cancellation, atomic transitions, and result correctness rather than machine-dependent timing assertions.

## Regression coverage

Fixtures cover 10,000 unannotated images, 2,000 Pascal VOC documents, 2,000 YOLO documents sharing one vocabulary, and one 10,000-record CreateML collection. Behavioral coverage includes portable nested-directory ordering, corrupt/removed files, refresh with dirty annotations, stop/resume, rapid directory replacement that rejects obsolete results, and quality summaries without full hashing.

Use focused cases in the [existing test runner](../../tools/run_tests.py) for deterministic I/O and growth checks; use the benchmark for ready-state, index-completion, and UI-publication timings. History, save targets, conflicts, annotation formats, and file-operation recovery retain their [existing contracts](undo-redo-and-file-recovery.md).
