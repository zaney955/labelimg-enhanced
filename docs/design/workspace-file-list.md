# Workspace and File List

This document owns file-list navigation, selection, display, and clipboard behavior. [Directory loading](large-directory-loading.md) defines readiness and incremental indexing; [history and recovery](undo-redo-and-file-recovery.md) defines persistence, external changes, and destructive transactions. Terms are in [CONTEXT.md](../../CONTEXT.md).

## Workspace and current image

An image directory supplies the workspace images. The annotation directory supplies their documents and save targets; when absent, the image directory serves both roles. Changing the annotation directory is a transactional workspace replacement, not a passive save-location preference. Standalone file opening loads one image or annotation document without implicitly opening its containing directory.

Opening an image directory selects the first row of its chosen sort order, regardless of annotation state. Reordering retains an already chosen current image by path and refreshes its position consistently in the window title and navigation controls.

The current image and file selection are independent. Opening or navigating never adds or removes selected files. List labels show paths relative to the workspace root, preserving nested directories; full absolute paths identify files and remain available on hover.

Separate image and annotation roots preserve relative subdirectories, with conventional `images/<split>` to `labels/<split>` matching even when opening one image split against the labels root. Existing flat annotations remain candidates; competing documents require explicit active-document selection. File operations use the same path policy. YOLO class mappings prefer the annotation-local `classes.txt`, then the `labels` root mapping, then the dataset root's `data.yaml` when class files are missing or empty. The conventional dataset boundary is the parent of the nearest `labels` or `images` ancestor; a flat layout uses its selected annotation directory (or the annotation file's own directory for standalone reads). Other ancestor `classes.txt`/`data.yaml` locations within that boundary require confirmation of their path and ordered class IDs in the UI before using the mapping or publishing a background index. Standard locations win over nonstandard locations. No configuration outside the boundary is used, including symlink/junction targets. Approval is scoped to the workspace and the exact configuration content; cancellation keeps the current image and annotations, and changed content requires a new confirmation. YAML ID mappings must be contiguous from zero and class names unique. The full ordered vocabulary, including unused classes, survives saves. Fallback class sources participate in fingerprints and current-document watching.

## Order, search, and filters

The chosen file-name, image-modification-time, annotation-state, or review-state ordering and direction produce one stable workspace sequence used by rows, visible navigation, and ordered batch commands. Relative directories remain natural-order batches, with natural filename order within each batch. Incremental state updates do not reorder rows.

Search is a session-only, case-insensitive literal substring of the complete filename, including extension, or separator-normalized relative display path. It combines with annotation, review, persistence-alert, and image-quality filters using AND. It does not use regular expressions, wildcards, fuzzy or Pinyin matching, image content, or external directories.

`Ctrl+F` focuses the persistent search field and selects its query from anywhere in the workbench. Typing filters live; Enter opens the first result and returns focus to the Canvas; clearing or Escape removes only the search condition. Fit to Window remains `Ctrl+0`. Search is available at directory ready state, survives refresh of that directory, and clears on image-directory change or exit.

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

During the system double-click interval, a prior selection may retain only its blue appearance to avoid flashing. Commands and counts already use the newly clicked file. Selected rows retain a light theme-accent background without a leading block after focus returns to the Canvas. Unselected hover uses neutral gray and preserves current-image and keyboard-focus indicators. Current-image emphasis is independent of selection.

## Status and review

The dock header shows a compact total or visible/total count and the current sort key and direction. A full-row annotation-directory button precedes the search field and filter button. Active advanced filters appear as removable chips; removing one preserves the other filters and search text, and Clear removes only advanced filters. Longer condition sets wrap into two rows. Counts and accessible tooltips include hidden current and selected images.

Selection-dependent actions appear in the bottom bar: rename and locate for one file, batch rename and review for multiple files, and a More menu using the same command builder as the context menu. Hidden selected files remain targets. Controls retain existing transaction confirmations, format restrictions, and shortcuts.

File rows have a minimum 26-pixel height and middle-elided relative paths. A narrow leading stripe and bold filename identify the current image independently of selection. The annotation-presence slot precedes the path; review and quality slots follow it. The rightmost slot is reserved for persistence, including the blue unsaved-change dot, even when the filename is long. Slots remain read-only; clicking them follows ordinary file selection/opening behavior.

| Dimension | States and presentation |
| --- | --- |
| Annotation presence | Hollow bounding box for one or more boxes; empty for no boxes |
| Review | Empty for unreviewed, amber circled question for questioned, green circled check for verified; full names on hover |
| Persistence | The rightmost slot shows the highest active severity: degraded, conflict, ambiguous document choice, dirty (blue dot); tooltip lists all conditions. A successful save clears dirty immediately, without a minimum display time. |

Annotation presence and review are independent: state selection and filters never infer one from the other. Persistence alerts do not modify filename text.

A retained dirty editing snapshot supplies the live annotation and review state, including a new document without a stored target. A later background disk index must not replace that state. Successful annotation saves, review transactions, image-processing commits, and recovery invalidate older index generations before publishing their updated projection; an interrupted projection rebuilds every row from the authoritative current workspace.

Current-image shortcuts toggle their verified or questioned state back to unreviewed when repeated. The always-visible top three-segment review control shows and sets one explicit state, independently of annotation-panel visibility. Batch commands set every selected image to one explicit state. [ADR 0010](../adr/0010-preserve-review-state-in-every-active-format.md) owns format-specific review storage.

## Clipboard transfer

Explicit file-list commands copy selected image files, their associated annotation resource set, or both to the system clipboard for another application to paste. They target the complete file selection context in view order, including hidden selected images; they do not write destination files.

Associated resources include every existing Pascal VOC, YOLO, and CreateML resource across both workspace annotation locations, deduplicating shared files even when those contain unselected image records. The operation neither chooses a format nor generates collection subsets. Resolve external conflicts first; unsaved current-image annotations may be saved or explicitly omitted in favor of stored bytes.

Missing annotation resources do not exclude available files. Annotation-only copying with no resources leaves the clipboard unchanged. Any unavailable selected image blocks the entire transfer without replacing the clipboard.

## File operations

Deleting the current image chooses the first surviving next image from the operation's original visible sequence, falling back to the nearest surviving previous visible image. It never navigates into a filtered-out row. Deleting other images preserves the current image. While the chosen replacement decodes, navigation is disabled and annotation-directory refreshes do not choose another image from a transient empty session. Deleting every visible image clears the Canvas if no visible replacement remains.

Delete and clear target images with all associated annotation formats; rename preserves directory and extension while changing basenames and embedded references together. Batch rename previews a unique mapping in pre-rename view order from prefix, original-name/sequence template, suffix, and unchanged extension. Transaction, rollback, unsaved-target handling, and recovery eligibility are specified once in [history and file recovery](undo-redo-and-file-recovery.md).

Implementation and verification start at [files](../../src/labelimg/files), [file tests](../../tests/files), and [workbench file-entry tests](../../tests/workbench/test_file_entry_ui.py).

## Cross-operation regression coverage

[Sorted workspace operation tests](../../tests/workbench/test_sorted_workspace_operations.py) exercise all eight combinations of name, modification time, annotation state, and review state ordering with ascending and descending direction. Every operation checks current image identity, full row order and path mapping, annotation/review badges, Canvas document and source pixels, and title/navigation counters against independently read fixture files. Unsaved edits use explicit expected live state.

| Area | Covered workflows |
| --- | --- |
| Opening and navigation | Synchronous/background opening at the first sorted row; previous/next navigation after mutations |
| File operations | Current first/middle/last deletion, other-file deletion, filtered/batch/all deletion, rename, annotation clearing, and recovery |
| Annotation editing | Paste/duplicate/delete the last box, undo/redo, manual save, autosave, and saving retained documents |
| Review | All three batch review states and recovery, single-image review, hidden selected targets and preserved filters |
| Image processing | Five rotation/flip commands, batch resize and pixel adjustment, crop that removes annotations, colored-frame removal, full/partial recovery, and non-destructive display adjustment/reset |
| Interrupted workflows | Canceled review/processing/crop, crop undo/redo, failed batch rollback, quality scan/clear, and edits/saves/review/crop/recovery while an old index is paused |

The matrix contains 45 operation variants per ordering mode, for 360 combinations in 28 test methods. It is also run against the installed DL package to verify the runtime copy.

All destructive operations run against temporary images and annotations. Dedicated directory-loading tests also retain worker ownership until thread completion and reject obsolete publication callbacks.
