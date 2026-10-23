# Workspace and File List

This document owns file-list navigation, selection, display, and clipboard behavior. [Directory loading](large-directory-loading.md) defines readiness and incremental indexing; [history and recovery](undo-redo-and-file-recovery.md) defines persistence, external changes, and destructive transactions. Terms are in [CONTEXT.md](../../CONTEXT.md).

## Workspace and current image

An image directory supplies the workspace images. The annotation directory supplies their documents and save targets; when absent, the image directory serves both roles. Changing the annotation directory is a transactional workspace replacement, not a passive save-location preference. Standalone file opening loads one image or annotation document without implicitly opening its containing directory.

Opening an image directory selects the first row of its chosen sort order, regardless of annotation state. Reordering retains an already chosen current image by path and refreshes its position consistently in the window title and navigation controls.

The current image and file selection are independent. Opening or navigating never adds or removes selected files. List labels show paths relative to the workspace root, preserving nested directories; full absolute paths identify files and remain available on hover.

Separate image and annotation roots preserve relative subdirectories, with conventional `images/<split>` to `labels/<split>` matching even when opening one image split against the labels root. Existing flat annotations remain candidates; competing documents require explicit active-document selection. File operations use the same path policy. YOLO class mappings prefer the annotation-local `classes.txt`, then the `labels` root mapping, then the dataset root's `data.yaml` when class files are missing or empty. The conventional dataset boundary is the parent of the nearest `labels` or `images` ancestor; a flat layout uses its selected annotation directory (or the annotation file's own directory for standalone reads). Other ancestor `classes.txt`/`data.yaml` locations within that boundary require confirmation of their path and ordered class IDs in the UI before using the mapping or publishing a background index. Standard locations win over nonstandard locations. No configuration outside the boundary is used, including symlink/junction targets. Approval is scoped to the workspace and the exact configuration content; cancellation keeps the current image and annotations, and changed content requires a new confirmation. YAML ID mappings must be contiguous from zero and class names unique. The full ordered vocabulary, including unused classes, survives saves. Fallback class sources participate in fingerprints and current-document watching.

### Annotation save targets

Manual saving and automatic saving use the same current annotation target, shown below the annotation-directory control with the full path on hover and in accessibility text. Editing a category, drawing another box, and introducing a new category do not change that target. Loading an existing document selects its actual format, including YOLO or CreateML when there is no XML. A new document uses the currently selected format. Explicitly changing format writes a separate document with the chosen extension and retains the previous format's file. Replacing an existing destination requires explicit selection in the save dialog; automatic saving pauses for that choice. Save As binds subsequent saves to the chosen path; a failed write keeps the original file intact and retains the requested destination for retry. Local and close-time batch saves temporarily release file-system watches to allow atomic file replacement on Windows, then restore watching even if the save fails; resource fingerprints still guard against external conflicts.

For the following examples, `a.ext` means `a.xml` (Pascal VOC), `a.txt` (YOLO), or `a.json` (CreateML).

| Opening and directory selection | New document | Existing document |
| --- | --- | --- |
| No annotation directory; image `data/a.png` | `data/a.ext` | Update that file |
| No annotation directory; image `data/category/a.png` | `data/category/a.ext` | Update that file |
| Both roots are `data`; image `data/category/a.png` | `data/category/a.ext` | Update the selected mapped or legacy flat file |
| Image root `photos`, annotation root `annotations`; image `photos/category/a.png` | `annotations/category/a.ext` | Update the selected mapped or legacy flat file |
| Image root `images`, annotation root `labels`; image `images/train/a.png` | `labels/train/a.ext` | Update that file |
| Image root `images/train`, annotation root `labels` | `labels/train/a.ext` | Update that file |
| Image root `images/train`, annotation root `labels/train` | `labels/train/a.ext` | Update that file |
| Standalone image, no annotation directory | Beside the image | Update the loaded file |
| Standalone image with an arbitrary annotation directory | Choose a destination with Save/Save As first | Update the loaded file |

An existing flat document remains in its original location when edited; ordinary saving does not migrate it into a subdirectory. Competing flat/mapped documents or multiple formats require active-document selection; canceling that selection does not write anything. When a separate annotation root is selected, annotations beside images outside that root are not implicit inputs. A standalone image without a known root mapping displays a pending destination and does not autosave into a guessed flat location. Canceling the first save leaves edits dirty and writes nothing; navigation and close-time saving must resolve that destination too. Flat layouts cannot distinguish identical image stems from different categories; use mapped subdirectories for those datasets.

YOLO uses append-only workspace class IDs. The shared `classes.txt` is at the selected annotation root (or image root when annotations are beside images), using the conventional `labels` ancestor when opening a split. Standalone saves outside the workspace use their destination directory. Existing local mappings must be compatible prefixes of one order; conflicting class IDs block saving and identify both configurations instead of silently renumbering existing annotations. Saving atomically publishes the annotation TXT, its adjacent `classes.txt`, and the shared mapping with conflict checks and rollback for the complete resource set. Shorter local mappings remain valid prefixes and are extended when that directory is saved. Unused IDs survive reopening; original YAML sources remain unchanged. Coordinated updates refresh peers' saved resource fingerprints while preserving each requested revision, source baseline, and output format.

A single-record `a.json` containing a short `a.png` reference is resolved through the same directory mapping as XML/TXT, preventing it from matching unrelated `a.png` images elsewhere. Other shared CreateML collections remain discoverable by their image references: updating a matched image preserves its record reference and the other records. A collection without a matching image record does not become the default target for that image; normal saving creates its per-image JSON. Qualified references distinguish same-named images in a shared collection.

Saving without boxes and without review state removes or avoids an empty Pascal VOC XML. YOLO retains an empty annotation TXT and its class mapping; CreateML retains an empty image record in JSON.

[Save-target matrix tests](../../tests/workbench/test_annotation_save_matrix.py) exercise actual workbench opening, category changes, box insertion, manual saving, and automatic-save callbacks across these layouts and all three formats. Additional cases cover empty documents, format conversion and overwrite confirmation, canceled and failed saves, close-time mixed-format saving, active-document selection, Save As, shared JSON collections, and same-named images in separate categories. [Workspace YOLO vocabulary tests](../../tests/annotations/test_workspace_yolo_vocabulary.py) cover class IDs across directories and reopening, incompatible mappings, external writes before/during staging, and rollback of a failed shared-mapping commit.

## Order, search, and filters

The chosen file-name, image-modification-time, annotation-state, or review-state ordering and direction produce one stable workspace sequence used by rows, visible navigation, and ordered batch commands. Relative directories remain natural-order batches, with natural filename order within each batch. Incremental state updates do not reorder rows.

Search is a session-only, case-insensitive literal substring of the complete filename, including extension, or separator-normalized relative display path. It combines with category, annotation, review, persistence-alert, and image-quality filters using AND. It does not use regular expressions, wildcards, fuzzy or Pinyin matching, image content, or external directories.

The filter button beside image search opens Advanced Filters. Its Annotation Categories section lists workspace categories with searchable checkboxes and two matching modes: Include All Selected Categories (the default) requires every selected category while allowing additional categories; Include Any Selected Category requires at least one. No selected categories means no category restriction. Category search is case-insensitive and changes only the checkbox rows; category identity and image matching use exact, case-sensitive labels. XML, YOLO, and CreateML contribute actual box labels, never unused YOLO vocabulary entries. Shared CreateML collections resolve labels separately for each image. Retained committed edits override saved labels; unresolved competing documents do not contribute a combined set of categories.

The popup uses the active theme's surfaces and accent, shared SVG icons, and compact input treatment. Category selection and State Conditions occupy separate bordered sections. The category header shows the selected count and a category-only clear action; its local search shares the leading search icon used by list queries. The category list grows with its visible rows up to five, scrolls longer lists, and reduces height when screen space is limited. All/Any matching uses an exclusive two-segment control with a live explanation. State conditions use a two-column grid with labels above their controls, and complete selected values remain available on hover. A separate footer states that filters apply immediately and offers Clear All Filters. Closing the popup preserves all conditions.

A category summary below image search states the matching mode and selected labels. Clicking its text reopens the filter editor; its adjacent clear button removes only the category condition. Long summaries elide visually and remain complete in tooltips and accessibility text. Clearing advanced filters also clears category selection and its local search while retaining image search; clearing all conditions clears both. When the last occurrence of a selected category disappears, the selected condition remains visible and can produce an empty result rather than silently widening the query. Category conditions survive refreshing the current directory, clear on workspace replacement, and are not persisted. Background index completion gates category filtering just like other annotation-dependent conditions. Committed edits, Undo/Redo, saving, and refreshed annotation state update the indexed category projection without rereading files on each filter change.

`Ctrl+F` focuses the persistent search field and selects its query from anywhere in the workbench. Typing filters live; Enter opens the first result and returns focus to the Canvas; clearing or Escape removes only the search condition. Canvas Fit to Window uses `Ctrl+Alt+0`; `Ctrl+0` resets [interface zoom](ui-scaling.md). Search is available at directory ready state, survives refresh of that directory, and clears on image-directory change or exit.

Filtering never replaces a nonmatching current image or drops hidden selected files. The UI explicitly reports hidden current and selected images. Previous/Next navigate visible images without wrapping; when the current image is hidden, they find the nearest visible image in the requested direction. State-dependent controls become available only when the required index is complete.

## File selection and appearance

| Input | Selection result |
| --- | --- |
| Ordinary click | Replace with that file immediately |
| Ctrl-click | Toggle one member |
| Shift-click | Select a contiguous visible range |
| File-list Ctrl+A | Replace with every visible file |
| Click empty list space | Clear selection |
| State-selection command | Replace with matching visible files in the chosen status dimension |
| Right-click selected file | Preserve the complete selection |
| Right-click unselected file | Replace with that file before opening commands |

During the system double-click interval, a prior selection may retain its selection appearance to avoid flashing; commands and counts already use the newly clicked file. The current image remains independent of selection. Selected-row styling follows the theme rules below; unselected hover preserves current-image and keyboard-focus indicators.

## Status and review

The dock header shows a compact total or visible/total count and the current sort key and direction. A full-row annotation-directory button precedes the search field and filter button. Active advanced filters appear as removable chips; removing one preserves the other filters and search text, and Clear removes only advanced filters. Longer condition sets wrap into two rows. Counts and accessible tooltips include hidden current and selected images.

Selection-dependent actions appear in the bottom bar: rename and locate for one file, batch rename and review for multiple files, and a More menu using the same command builder as the context menu. Hidden selected files remain targets. Controls retain existing transaction confirmations, format restrictions, and shortcuts.

File-row height is the greater of 32 logical pixels or the font height plus ten pixels. Relative paths are middle-elided. A narrow leading stripe and bold filename identify the current image independently of selection. The annotation-presence slot precedes the path; review and quality slots follow it. The rightmost slot is reserved for persistence, including the blue unsaved-change dot, even when the filename is long. Slots remain read-only; clicking them follows ordinary file selection/opening behavior.

| Dimension | States and presentation |
| --- | --- |
| Annotation presence | Hollow bounding box for one or more boxes; empty for no boxes |
| Review | Empty for unreviewed, amber circled question for questioned, green circled check for verified; full names on hover |
| Persistence | The rightmost slot shows the highest active severity: degraded, conflict, ambiguous document choice, dirty (blue dot); tooltip lists all conditions. A successful save clears dirty immediately, without a minimum display time. |

Annotation presence and review are independent: state selection and filters never infer one from the other. Persistence alerts do not modify filename text.

A retained dirty editing snapshot supplies the live annotation and review state, including a new document without a stored target. A later background disk index must not replace that state. Successful annotation saves, review transactions, image-processing commits, and recovery invalidate older index generations before publishing their updated projection; an interrupted projection rebuilds every row from the authoritative current workspace.

Current-image shortcuts toggle their verified or questioned state back to unreviewed when repeated. The Canvas upper-right review control shows and sets one explicit state, independently of annotation-panel visibility or docking position. All segments retain their text and stable geometry when the state changes. Its continuous translucent ribbon replaces whole-Canvas background tinting; [command surfaces](canvas-tool-rail.md#top-command-surface) define appearance, mouse transparency, and live theme/language behavior. Undo and Redo refresh the same review projection. Batch commands set every selected image to one explicit state. [ADR 0010](../adr/0010-preserve-review-state-in-every-active-format.md) owns format-specific review storage.

Selected rows use an opaque, softly tinted background and a thin rounded outline. This remains visible when focus moves to batch commands or menus; hover does not fade it. The current image retains its separate stripe and bold filename. The theme owns `selection_background`, `selection_border`, and `selection_foreground`; the delegate never fades the already-tinted QSS Highlight again. Selected filename contrast remains at least 4.5:1, while fill and outline strength have upper bounds to keep multi-selection restrained.

## Clipboard transfer

Explicit file-list commands copy selected image files, their associated annotation resource set, or both to the system clipboard for another application to paste. They target the complete file selection context in view order, including hidden selected images; they do not write destination files.

Associated resources include every existing Pascal VOC, YOLO, and CreateML resource across both workspace annotation locations, deduplicating shared files even when those contain unselected image records. The operation neither chooses a format nor generates collection subsets. Resolve external conflicts first; unsaved current-image annotations may be saved or explicitly omitted in favor of stored bytes.

Missing annotation resources do not exclude available files. Annotation-only copying with no resources leaves the clipboard unchanged. Any unavailable selected image blocks the entire transfer without replacing the clipboard.

## File operations

Deleting the current image chooses the first surviving next image from the operation's original visible sequence, falling back to the nearest surviving previous visible image. It never navigates into a filtered-out row. Deleting other images preserves the current image. While the chosen replacement decodes, navigation is disabled and annotation-directory refreshes do not choose another image from a transient empty session. Deleting every visible image clears the Canvas if no visible replacement remains.

Delete and clear target images with all associated annotation formats; rename preserves directory and extension while changing basenames and embedded references together. Batch rename previews a unique mapping in pre-rename view order from prefix, original-name/sequence template, suffix, and unchanged extension. Transaction, rollback, unsaved-target handling, and recovery eligibility are specified once in [history and file recovery](undo-redo-and-file-recovery.md).

Implementation and verification start at [files](../../src/labelimg/files), [file tests](../../tests/files), and [workbench file-entry tests](../../tests/workbench/test_file_entry_ui.py).

## Cross-operation regression coverage

[Sorted workspace operation tests](../../tests/workbench/test_sorted_workspace_operations.py) cover name, modification-time, annotation-state, and review-state sorting in both directions. They check current-image identity, row order/path mapping, status badges, Canvas geometry/pixels, and navigation counters against temporary fixture files, including expected live unsaved state.

The suite spans navigation, file mutation/recovery, annotation edits and saving, individual/batch review, image processing/recovery, hidden selections, cancellation/rollback, quality checks, and races with paused indexes. Dedicated loading tests retain worker ownership until completion and reject obsolete callbacks. The test modules define the current variants; use the [development guide](../development.md) to validate a specific source or installed package.
