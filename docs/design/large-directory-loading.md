# Large-directory loading

Current progressive-loading contract; timing targets are verified separately from deterministic correctness tests.

## Outcome

Opening an image directory or changing its annotation directory becomes usable at **directory ready state**, before **workspace index completion**. The normal workload is 10,000 local images with annotations; 50,000 images must still support responsive navigation, cancellation, editing, and visible-list interaction, without a fixed completion-time promise.

The index exists only in memory for the current application session. [ADR 0024](../adr/0024-open-large-directories-progressively-with-session-only-indexes.md) records this decision; [ADR 0025](../adr/0025-synchronize-only-the-current-annotation-document.md) limits external document synchronization.

## User-visible semantics

### Directory ready state

A new workspace commits only when it can atomically install the image and annotation directories, stable naturally ordered discovered-file list, loadable current image and annotation document, and authoritative save target. Until then, the previous workspace remains intact.

The complete discovered image sequence remains authoritative for navigation and counters while list rows are published in batches. Refreshing a published row never replaces that sequence with the visible row prefix; row lookup tracks published positions independently from workspace positions.

Opening a directory defaults to its first image in the selected file-list sort order, independent of annotation presence. If that order depends on background annotation/review indexing, completion resolves the initial image to the first final row only while the user has neither navigated nor edited. Title and command-bar counters always follow the current image's position after sorting, including before the next navigation command.

Editing, saving, name search, and navigation become available at this point. Navigating to a file whose annotation state is not indexed prioritizes its exact annotation load; placeholder state is never editable.

### Workspace index completion

Annotation, review, ambiguity, and persistence states arrive progressively. Badges may update, but rows do not move as results arrive. State-dependent controls remain disabled with visible indexing progress until their required data is complete; incomplete sorting or filtering results are never presented as authoritative.

Image-quality content validation is a separate explicit operation. Opening a directory may bulk-load quality-cache summaries but does not hash every image.

### Progress, cancellation, and errors

Progress is non-modal, for example `Discovered X · Indexed Y`. Each load has a monotonically increasing generation identity. Selecting another directory immediately invalidates the prior generation; late results are discarded. Explicit stop leaves an already-ready workspace usable with an incomplete index and offers resume.

Progress and Stop/Resume occupy the middle of the [unified workbench status bar](canvas-tool-rail.md#unified-workbench-status). They remain ahead of operation-result and hover messages until the task completes or is invalidated. Failures persist with a Details command and Resume; live language changes update both task copy and button text without altering the task state. Completion removes the task controls and returns the middle region to operation feedback without moving zoom.

Resume preserves the request kind and arguments: an annotation-directory request restarts annotation indexing rather than reopening the previous image directory. Progress transitions and completion discard queued ordinary results, preventing old file/category messages from resurfacing after a task.

A corrupt or disappearing non-current file contributes to an aggregated warning without aborting the load. If the proposed current image cannot load, the coordinator tries the next usable image. Repeated errors do not open one modal dialog per file.

Application-owned file operations update the index immediately. Debounced metadata differences in the watched annotation directory update only affected image statuses and candidate-label contributions. Other external changes appear through refresh, reopening, or access to the affected file; directory events never trigger a full synchronous rescan.

Selecting the current annotation directory again explicitly rebuilds its index, including YOLO statuses previously inspected without a class mapping. Both synchronous and background entry points publish refreshed annotation badges for every image without requiring image navigation. Refresh preserves current image, selection, filters, Canvas view, history, and unsaved edits. A dirty current document is not replaced; its external changes use the [synchronization and conflict contract](undo-redo-and-file-recovery.md#external-conflicts).

## Architecture

| Owner | Responsibility |
| --- | --- |
| [files.application.discovery](../../src/labelimg/files/application/discovery.py) | Qt-free recursive image discovery and portable natural-sort keys. |
| [annotations.application.workspace](../../src/labelimg/annotations/application/workspace.py) | Resource indexing and immutable per-image snapshots. |
| [workbench](../../src/labelimg/workbench/main_window.py) | Atomic workspace transition and authoritative active document. |
| [files.ui.loading](../../src/labelimg/files/ui/loading.py) | Workers, generations, progress, stop/resume, and bounded publication. |
| [files.ui.list_widget](../../src/labelimg/files/ui/list_widget.py) | Virtualized `QAbstractListModel` and proxy filtering/sorting. |

Worker ownership lasts until the QThread finishes, rather than only until the scan function emits its completion signal. Closing the workbench invalidates queued results and waits for directory workers to stop; a timeout leaves the window open.

Workers discover and sort paths, then build remaining annotation snapshots without mutating the active workspace. Every queued path/status publication also carries its originating generation. File mutations invalidate outstanding discovery/index projections before pumping UI events, so old results cannot replace the updated file list. The UI thread checks the generation and applies results through their authoritative owner. Application and domain modules neither import Qt nor expose Qt thread types.

One per-image snapshot supplies document choices, active choice, annotation/review state, ambiguity/persistence flags, candidate-label contribution, and resource fingerprints. File-list population consumes this bulk state instead of independently querying each property.

The index avoids repeated work:

- Compute each relative natural-sort key once, sort discovery once, and reuse the default-name order. Read image modification times only when the chosen sort requires them.
- Read each physical annotation resource once per build; parse, hash, and retain recovery bytes from that byte sequence. Deduplicate shared YOLO vocabularies.
- Use path-to-snapshot and path-to-row dictionaries. Build CreateML exact-reference and legacy-basename indexes once; resolution and candidate aggregation do not scan every collection record for each image.
- Load quality-cache summaries once without full-image hashing. A startup directory follows one import transition.
- Publish stable file order, then bounded immutable state batches. The virtualized list preserves selection, range selection, context menus, keyboard navigation, drag behavior, and file-operation semantics.

## Performance budget

The opt-in [benchmark](../../tools/benchmark_directory_loading.py) exercises real image- and annotation-directory transitions with local PNG/Pascal VOC fixtures, excluding fixture creation. Run it in the target environment and report the checkout, interpreter, workload and measured timings; past results are not current performance guarantees.

| 10,000-file milestone | Target |
| --- | ---: |
| Directory ready state | < 0.500 s |
| Workspace index completion | < 5.000 s |
| Longest UI publication batch | <= 0.050 s |

Publication uses 64-row batches. No uninterrupted UI-thread task should exceed 50 ms; discovery, annotation resolution, status lookup, and row lookup must avoid quadratic call-count growth. Synchronous compatibility-path timings are diagnostic only. CI checks resource reads, bounded growth, generation cancellation, atomic transitions, and correctness rather than machine-dependent timing.

## Interactive operations

### Progressive image navigation

Large images first decode at a native 1/2, 1/4 or 1/8 resolution that covers the fitted viewport at its device-pixel ratio, with 25% headroom. Small images keep their direct full-resolution path. JPEG performs reduced decoding; other Qt-supported formats may still require a full internal decode before producing bounded display pixels.

Large PNGs additionally use lossless, disposable RGBA previews on disk. Actual file encoding determines eligibility, not the extension. Opening a directory starts one cancellable preparation worker; switching directories replaces its remaining queue, and closing the window stops further work. Preparation never loads annotations or edits source files. Neighbor prefetch and explicit navigation share content-keyed preparation across windows, and foreground requests take priority over queued speculative full decodes. A running Qt decode finishes before yielding.

Temporary decode memory has its own admission budget, separate from the small preview LRU. Only one heavy decode runs at a time per process. Speculative decodes require at most one quarter of currently available memory, capped at 1 GiB; explicit requests may proceed exclusively even above that speculative limit. Low-memory conditions skip background preparation rather than multiplying full-image allocations.

The disk key includes the source-byte SHA-256, preview dimensions and decoder schema. Every disk hit reads and hashes the current source off the GUI thread, checks its version and prepares the normal source fingerprint; preserved filenames, sizes or timestamps cannot bind old pixels to a new source. Preview files use bounded lossless decompression, preserve alpha, and are published by atomic replacement. Missing, corrupt, incompatible or unwritable cache entries fall back to source decoding. Save-time conflict verification and original annotation geometry remain unchanged.

Small file-version hints allow directory preparation to skip sources already prepared at the requested pixel size. These hints authorize only skipping background work, never displaying pixels: explicit navigation still hashes the current source and validates its fingerprint. A same-token replacement may need a fresh decode when first visited, but cannot reuse stale pixels. Hints share the cache's quota and cleanup policy.

The default cache is `%LOCALAPPDATA%/LabelImg/preview-cache-v1` on Windows or `$XDG_CACHE_HOME/LabelImg/preview-cache-v1` (default `~/.cache`) elsewhere. Isolated settings use `LABELIMG_CONFIG_DIR/preview-cache-v1`; `LABELIMG_PREVIEW_CACHE_DIR` overrides either location. LRU cleanup limits recognized entries to 2 GiB and 4096 files; previews above 16 megapixels are not persisted. Old crash temporary files are removed after a day. With LabelImg closed, removing this directory is safe; it contains no source images or annotations. `PreviewDiskCache().prune(clear=True)` clears only recognized cache entries. The directory/annotation index remains session-only, as specified in ADR 0024.

Cold PNGs still need a first full decode; preparation cannot promise JPEG latency before previews exist. Report cold, prepared and new-process cache-reuse timings separately. The benchmark accepts `--start-prefix ZX_`, a persistent `--preview-cache-dir`, and `--prepare-previews` to distinguish these workloads.

The pixel cache separates previews from full images under the available-memory budget. Two prefetch workers prepare four visible neighbors in the navigation direction and two in reverse order; the on-demand navigation worker can serve an explicit destination without waiting behind unrelated queued prefetch. Queued obsolete work is cancelled. Navigation follows the sorted/filtered projection and continues to coalesce repeated A/D requests into the next displayed frame, without accumulating unseen steps. Each successful indexed transition repaints the Canvas before accepting the next queued key, preventing Qt from merging adjacent frames that were loaded but never displayed.

Both held keys and discrete taps restart a 300 ms idle timer. After navigation settles, a single refinement worker prepares the current original image. Zooming beyond the preview's pixel density requests detail immediately. Refinement validates generation, path, source token, fingerprint and original dimensions before replacing only Canvas pixels; it preserves boxes, selection, zoom, view position, edits, review state and undo history. A failed refinement keeps the existing view and reports a reading error in the status bar. Pixel tools that require a full source prepare it through the existing cancellable preparation flow.

`ImageMetadata` carries original, EXIF-oriented geometry separately from display pixels. Annotation formats consume that geometry for coordinates and saved dimensions even before refinement finishes. Source identity is prepared using original dimensions and retained across pixel levels; strict save-time verification is unchanged. Replaced/invalidated sources retire their decoded pixels in both tiers so stale buffers cannot establish a new clean baseline. Worker completion cannot publish into a closed or replaced workbench.

The opt-in `tools/benchmark_navigation.py DIRECTORY --gesture tap --output report.json` uses isolated settings and annotation targets and never changes the supplied images. It verifies the sequence of **painted** frames, records request-to-paint latency, frame intervals and GUI heartbeat, then checks full-resolution settling. Use `--gesture hold` for keyboard auto-repeat and `QT_QPA_PLATFORM=windows` for native Windows verification. Cold startup, direction changes, autosave, image replacements, rotated JPEGs and retained annotation state are covered separately; decoder-only timings do not establish end-to-end smoothness.

Warm image navigation reuses a source-versioned decoded image and its prepared content fingerprint. A hit performs lightweight source-token checks rather than hashing the original image on the GUI thread. Cold large images prepare both pixels and identity off-thread. Background verification of unchanged metadata is coalesced and cannot publish an obsolete identity or displace the latest navigation request. Save-time content verification remains independent. Regression tests check thread ownership, repeated warm previous/next navigation, metadata-preserving replacements, and stale background results; opt-in high-resolution timings report navigation-call and paint-inclusive latency separately.

Filtering publishes row visibility to the proxy once per query, then restores the final selection in contiguous ranges. Hidden selections survive filtering. Select all, invert, Shift ranges, double-click restoration, status-based selection, rename and recovery project one final selection instead of one notification per row. Changing only a filter reuses the established default-name order; state sorting computes each natural path key once per projection.

Annotation group visibility updates the Canvas and group-list state once per gesture. Canvas painting is queued so hiding or showing a category does not synchronously repaint the entire image for every box.

Deletion removes only successfully deleted paths from the known workspace sequence and reuses surviving row objects. Failed images remain selected; shared-document changes refresh affected survivor states. Interrupted indexing finishes the remaining states before enabling advanced filters. Deleting unannotated images does not rescan the annotation directory. Other external filesystem changes continue to appear through refresh/reopening/access, rather than implicit directory rediscovery after every deletion.

Recovery identities are merged using a path index, preserving the first recoverable original and latest post-operation fingerprint for shared resources. Windows recycle-location probes are reused only within one synchronous operation and directory identity; standalone calls and subsequent operations probe again. Actual deletes still require an actionable Shell identity, and per-image locking, rollback and cancellation remain in effect.

Run `python tools/benchmark_interactions.py --count 3000 --delete-count 500` for an opt-in comparison of filtering, selection, state sorting, 500-box visibility and deletion with disposable files. `--package-root` selects an extracted wheel. This benchmark includes queued Qt paint/layout work; its rename-based trash adapter measures application overhead, not Windows Shell or network throughput. Deterministic regressions assert bounded row evaluation, selection notifications and recovery bookkeeping instead of machine-specific timing thresholds.

## Regression coverage

Fixtures cover 10,000 unannotated images, 2,000 Pascal VOC documents, 2,000 YOLO documents sharing one vocabulary, and one 10,000-record CreateML collection. Behavioral coverage includes portable nested-directory ordering, corrupt/removed files, refresh with dirty annotations, stop/resume, rapid directory replacement that rejects obsolete results, and quality summaries without full hashing.

Use [focused unittest discovery or the full runner](../development.md#源码与定向测试) for deterministic I/O and growth checks; use the benchmark for ready-state, index-completion, and UI-publication timings. History, save targets, conflicts, annotation formats, and file-operation recovery retain their [existing contracts](undo-redo-and-file-recovery.md).
