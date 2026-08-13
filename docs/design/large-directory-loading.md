# Large-directory loading

Status: implemented and measured in the `DL` environment.

## Outcome

Opening an image directory or changing its annotation directory must not freeze the interface while every file is discovered, parsed, fingerprinted, and projected into the file list. The workspace becomes usable at **directory ready state** and reaches **workspace index completion** later.

The target workload is 10,000 local images with corresponding annotations as a normal workspace. A 50,000-image workspace must remain usable through progressive loading and a virtualized file list. The workspace index is memory-only: it is not written to disk and is not reused by another application session.

## Measured baseline

The diagnostic harness used the real `MainWindow.import_dir_images()` and `MainWindow._switch_annotation_directory()` entry points in the `DL` Conda environment with Python 3.14.2. Fixtures were small local PNG and Pascal VOC XML files; fixture creation was excluded from timing.

| Files | Open image directory | Switch annotation directory |
| ---: | ---: | ---: |
| 1,000 | 0.660 s | 2.115 s |
| 2,000 | 1.330 s | 4.194 s |
| 3,000 | 2.168 s | 6.310 s |

After implementation, the same 3,000-file fixture completes the synchronous compatibility paths in approximately 0.55 seconds and 1.10 seconds respectively. The progressive path reaches directory ready state in approximately 0.11 seconds and completes its session index in approximately 1.20 seconds.

The agreed 10,000-file workload measured:

| Measurement | Result | Target |
| --- | ---: | ---: |
| Directory ready state | 0.214 s | < 0.500 s |
| Workspace index completion | 3.853 s | < 5.000 s |
| Longest measured UI publication batch | 0.039 s | <= 0.050 s |
| Synchronous image-directory compatibility path | 1.747 s | Report only |
| Synchronous annotation-directory compatibility path | 3.366 s | Report only |

UI publication uses 64-row batches to retain margin below the 50 ms responsiveness budget. `tools/benchmark_directory_loading.py` is the opt-in reproduction command.

A profiled 1,000-file run measured 2.518 seconds for annotation-directory switching. `refresh_file_list_statuses()` accounted for 1.500 seconds and `AnnotationWorkspace.scan()` for 0.995 seconds. The run made 4,001 `AnnotationWorkspace.entry()` calls, 3,000 full annotation inspections, approximately 11,000 file opens, and approximately 13,700 stats. Profiling overhead makes its wall-clock values unsuitable for comparison, but the call counts identify the repeated work.

## Causes

The delay is not thumbnail generation; the file list does not load thumbnails. It is the accumulated synchronous work below:

- image discovery recursively walks the directory and performs an expensive comparator-based natural sort;
- the file-list projection naturally sorts the same paths again and reads every image modification time even when sorting by name;
- annotation state and review state independently call `AnnotationWorkspace.entry()`, causing the same annotation to be inspected twice per row;
- persistence flags perform another document-choice and filesystem query per row;
- annotation-directory scanning parses a resource, reads it again to hash it, and reads it again to retain its bytes;
- a shared YOLO `classes.txt` can be reread for every annotation;
- CreateML image resolution and some candidate-label queries scan all records for each image and can approach quadratic growth;
- annotation-directory refresh uses membership and `list.index()` per image, producing another quadratic path;
- the quality cache is opened and decoded per row and can hash the full image on a cache hit;
- `QListWidgetItem` instances and several full-list projections are created synchronously on the UI thread;
- a directory supplied at startup can schedule and immediately invoke the same import path, potentially loading it twice.

## User-visible semantics

### Directory ready state

The application may commit a new workspace only after it can atomically install:

- the selected image directory and annotation directory;
- a stable, naturally ordered discovered-file list;
- a loadable current image and its corresponding annotation document;
- the authoritative save target for that annotation document.

Editing, saving, name search, and file navigation are enabled at this point. Navigating to a file whose annotation state is not indexed prioritizes that file's exact annotation load. Placeholder state is never editable.

### Workspace index completion

Annotation, review, ambiguity, and persistence states are incorporated after directory ready state. Controls that depend on incomplete state remain disabled and show indexing progress rather than presenting incomplete results as authoritative. State badges may update progressively, but rows do not move as results arrive. Dependent sorting and filtering become available when their required index is complete.

Image-quality validation is not part of workspace index completion. Directory opening may bulk-load cache summaries but must not hash every image. Content validation occurs only during an explicit image-quality operation.

### Progress, cancellation, and errors

Indexing uses non-modal progress such as `Discovered X · Indexed Y`. Choosing another directory invalidates the current loading generation immediately. An explicit stop leaves the ready workspace usable, marks its index incomplete, and offers resume.

Each load carries a monotonically increasing generation identity. Only results matching the active generation may be applied. Late results from a canceled or superseded load are discarded.

A corrupt or disappearing non-current file becomes one aggregated warning and does not abort the load. If the proposed current image cannot load, the coordinator tries the next usable image. Repeated errors are summarized rather than shown as one modal dialog per file.

The index observes a directory snapshot. Application-owned file operations update it immediately. External filesystem changes are incorporated by manual refresh, reopening the directory, or detecting the change when the affected file is accessed; filesystem watching is outside this design.

Refreshing preserves the current image, file selection, filters, Canvas view, annotation history, and unsaved edits. It does not replace a dirty current document. An external change to that document enters the existing conflict workflow.

## Architecture

The implementation follows existing feature boundaries:

- `files.application` owns Qt-free image discovery and precomputed portable natural-sort keys;
- `annotations.application` owns annotation resource indexing and immutable per-image workspace snapshots;
- `workbench` coordinates the atomic workspace transition;
- `files.ui` and `workbench` UI adapters own worker lifecycle, loading generations, progress, cancellation, and Qt model projection;
- application and domain modules do not import Qt or expose Qt thread types.

Worker code builds immutable results without mutating the active workspace. The UI thread verifies the generation identity and applies a result through the authoritative owner. A directory-ready commit is one explicit workspace transition, not a sequence of independent widget mutations.

The per-image snapshot combines the values currently queried separately:

- candidate annotation documents and the active choice;
- annotation and review state;
- ambiguity and persistence flags;
- labels required for candidate-label aggregation;
- recoverable resource fingerprint information required by existing conflict behavior.

Path-to-snapshot and path-to-row mappings provide constant-time lookup. CreateML collections additionally maintain exact and legacy image-identity indexes so resolving every image does not scan every record.

## Phase 1: remove repeated work

Phase 1 established deterministic performance seams and improved the synchronous path before concurrency was introduced.

1. Extract recursive image discovery from the UI controller into `files.application`. Compute each relative natural-sort key once and perform one sort.
2. Add an annotation index builder that reads each physical resource once per build. Parse, hash, and retain required recovery bytes from that one byte sequence. Deduplicate shared resources such as YOLO `classes.txt`.
3. Build CreateML reverse indexes once and compute candidate labels once per completed annotation snapshot.
4. Expose one bulk per-image snapshot query. File-list population must not independently query annotation, review, and persistence state.
5. Remove repeated list membership and `list.index()` calls in status refresh. Maintain dictionaries for row and state lookup.
6. Do not request image modification times unless the active sort requires them. Do not naturally sort an already ordered default-name projection again.
7. Bulk-load the quality-cache summary once. Do not hash image contents during directory opening.
8. Remove the duplicate startup directory import if the queued and immediate paths are confirmed to target the same transition.

Phase 1 may remain synchronous temporarily, but it is incomplete until resource-read counts and growth tests pass. Its APIs must support Phase 2 without moving Qt into application modules.

## Phase 2: progressive UI loading

1. Add a UI-owned loading coordinator with generation-based cancellation.
2. Discover and naturally sort paths off the UI thread. Publish the stable file order once.
3. Load the proposed current image and exact annotation document, then atomically commit directory ready state.
4. Build remaining annotation snapshots off the UI thread. Prioritize navigation requests and publish bounded immutable batches.
5. Replace the eager `QListWidget` file collection with `QAbstractListModel` and proxy-model filtering/sorting. Preserve current selection, range selection, context menus, keyboard navigation, drag behavior, and file-operation semantics.
6. Apply bounded batches so no UI-thread task exceeds the responsiveness budget. Expose non-modal progress, stop, and resume.
7. Enable state-dependent controls only after their required index reaches completion.

## Acceptance criteria

On the agreed 10,000-file local workload:

- no uninterrupted UI-thread task exceeds 50 ms;
- directory ready state is reached within 500 ms;
- workspace index completion is reached within 5 seconds;
- the interface remains interactive throughout indexing;
- each physical annotation resource is read at most once per index build;
- directory discovery, image-to-annotation resolution, status lookup, and row lookup contain no operation whose call count grows quadratically with the number of images or annotation records.

The 50,000-image workload has no fixed completion-time promise, but navigation, cancellation, editing of a ready document, and visible-list interaction must remain responsive.

Wall-clock thresholds are recorded in the `DL` environment and reported separately from correctness tests. CI primarily asserts deterministic resource-read counts, bounded call-count growth, generation cancellation, atomic transitions, and result correctness so slower runners do not produce false failures.

## Regression matrix

The automated fixtures cover:

- 10,000 images without annotations;
- 2,000 Pascal VOC XML documents;
- 2,000 YOLO documents sharing one `classes.txt`;
- one CreateML collection containing 10,000 records;
- nested directories and portable natural ordering;
- corrupt annotations and files removed during scanning;
- refresh with a dirty current annotation document;
- explicit stop and resume;
- rapid selection of two directories, proving that the first generation cannot affect the second;
- image-quality cache summaries without full image hashing.

The first feedback-loop command should remain a single isolated test entry in the existing runner style, with deterministic I/O and call-count assertions as the red/green signal. A separate opt-in benchmark uses the real offscreen Qt entry points to report directory-ready, index-completion, and longest-UI-task timings in the `DL` environment.

## Excluded work

- no persistent or cross-session index;
- no whole-workspace filesystem watcher; only the current image's active annotation resource is watched;
- no incomplete state-dependent filter results;
- no row reordering while incremental annotation states arrive;
- no full-image quality validation during directory opening;
- no change to annotation formats, save-target rules, conflict handling, or file-operation recovery semantics.
