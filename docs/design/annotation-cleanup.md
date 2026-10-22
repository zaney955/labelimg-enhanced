# Annotation file cleanup

**Tools → Clean Annotation Files…** maintains the selected image/annotation directory pair. It has one menu entry, no shortcut, and no Canvas or file-row context-menu entry. It becomes available when an image workspace and an existing annotation directory are open; annotations beside images are supported.

## Preview and selection

Opening the dialog does not change files. Scan recursively discovers supported image extensions from disk, independently of list selection, search, category filters, and incomplete background indexing. It shows both directory roots, the effective scan locations, image/candidate/selected/skipped counts, relative annotation paths with full-path tooltips, and cleanup reasons. Invalid or unreadable files appear separately in Skipped Files. Canceling a scan discards its partial plan.

Candidates fall into two selectable categories:

- **Without matching images**: selected by default. Match extensions independently of image format and preserve relative subdirectories, conventional `images`/`labels` splits, and existing flat annotations. Opening `images/train` against `labels` scans `labels/train` recursively plus flat files directly in `labels`, preserving other splits.
- **Empty annotations**: initially unselected. Identify zero-byte files, whitespace-only files, and recognized VOC/YOLO/CreateML documents without annotation objects. YOLO review-only comments and VOC/CreateML review metadata can remain in these files. Empty annotations may be intentional negative samples; removing them requires explicit selection.

Each candidate can be checked independently; category checkboxes select or clear their category. Scanning again rebuilds the preview and selection from the category choices.

`classes.txt`, `predefined_classes.txt`, YAML configurations, unsupported extensions, symbolic-link/junction files and descendant directories are preserved. Nonempty unrecognized or malformed XML/TXT/JSON files are skipped rather than treated as empty. No category mapping is needed or modified by the scan.

CreateML uses record references, including qualified references and shared collections. A short single-record same-stem JSON uses the existing directory mapping. A collection with any matching image is not an orphan; a collection with any annotation object is not empty. Cleanup removes whole files only, preserving mixed collections containing useful records.

## Execution and recovery

The final confirmation states the exact selected count, preservation of images, negative-sample/review-state implications, affected history reset, and recovery entry. The default answer is No.

Execution checks the workspace roots, blocks unsaved image histories or shared-resource edits touching selected files, preflights system Recycle Bin support, and rescans the directory pair to verify file fingerprints and image associations. Changed files or a newly added corresponding image invalidate the reviewed candidate. Each move checks the file fingerprint and path boundary again under the workspace storage lease. File watches and autosave cannot interfere with the operation.

Only selected annotation files move to the system Recycle Bin. Cancellation and per-file failures preserve a recovery entry for already completed moves. Successful files refresh candidate categories, file-list status, and the current image; their affected clean editing histories are discarded. Unrelated unsaved edits remain intact.

**File → Recent File Operations** lists Clean annotation files and recovers the complete recorded batch. Recovery protects dirty annotation resources, validates trash identities, and refuses to overwrite recreated destinations. Session recovery has the existing platform limitation: when the system cannot supply actionable trash identities, restore manually from the system Recycle Bin.
