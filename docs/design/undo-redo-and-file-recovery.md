# Undo, Redo, Save Coordination, and File Recovery Design

Status: implemented. This document owns the detailed history, persistence, synchronization, and recovery contracts.

## Outcome

LabelImg Enhanced has two recovery systems:

1. Per-image annotation Undo and Redo for current-image document edits.
2. A session-only recent file operations center for cross-file deletion, annotation clearing, synchronized rename, and batch review-state recovery.

`Ctrl+Z`, `Ctrl+Y`, and `Ctrl+Shift+Z` operate only on the current image's annotation history. They never restore deleted files, reverse file-list selection, or undo a batch file operation. File operation recovery is explicit from the File menu and always confirms before changing the filesystem.

The [glossary](../../CONTEXT.md) defines the vocabulary. Decisions and rejected alternatives are recorded in [ADR 0007](../adr/0007-make-file-list-batch-operations-annotation-aware-and-recoverable.md), [0008](../adr/0008-use-bounded-document-snapshots-for-annotation-history.md), [0009](../adr/0009-coordinate-annotation-saves-by-physical-resource.md), [0010](../adr/0010-preserve-review-state-in-every-active-format.md), [0011](../adr/0011-close-edit-and-filesystem-transactions-at-explicit-boundaries.md), [0012](../adr/0012-copy-windows-recycle-identities-as-pidls.md), and [0025](../adr/0025-synchronize-only-the-current-annotation-document.md).

## Scope

Annotation history includes:

- create a labeled box;
- delete one or many selected boxes;
- duplicate selected boxes;
- paste boxes;
- copy the previous image's boxes;
- move, resize, edge drag, vertex drag, and arrow-key nudge;
- edit a box label or difficult flag;
- change the current image review state.

Annotation history excludes:

- Canvas and label-list selection;
- box visibility;
- zoom, pan, filters, hover, and editing mode;
- the session label color palette and other view preferences;
- copying without pasting;
- image navigation and file-list selection;
- output format and destination path;
- global candidate-label and YOLO vocabulary maintenance;
- load-time clamping of out-of-bounds coordinates;
- every cross-file operation.

## Architecture

The domain and application owners are Qt-free; Canvas and workbench adapters project their results.

| Owner | Responsibility |
| --- | --- |
| [AnnotationHistory](../../src/labelimg/annotations/domain/history.py) | Immutable per-image histories, cursors, revisions, saved baselines, retention, and branches. |
| [AnnotationEditingController](../../src/labelimg/annotations/application/editing.py) | The annotation mutation boundary: capture, commit/cancel, Undo/Redo, and derived-state updates. |
| [Canvas scene and shortcut adapters](../../src/labelimg/annotations/ui/controller.py) | Guarded Canvas/label-list capture, projection, and history shortcut routing. |
| [AnnotationWorkspace](../../src/labelimg/annotations/application/workspace.py) | Document choice, format adapters, candidate labels, YOLO vocabulary, image/resource mapping, and workspace identity. |
| [AnnotationSaveCoordinator](../../src/labelimg/annotations/application/persistence.py) | Revision-bound saves, resource grouping, fingerprints, conflicts, and exact baseline acknowledgement. |
| [ReviewStateTransaction](../../src/labelimg/annotations/application/review.py) | Cross-file review changes, leased revalidation, recovery records, and rollback. Forward batches allow partial success; recovery is atomic. |
| [AnnotationStorageCoordinator](../../src/labelimg/annotations/infrastructure/storage.py) | Resource leases and atomic physical replacement. |
| [FileOperationTransaction](../../src/labelimg/files/application/transaction.py) | Clear, delete, rename, recovery, resource preflight, trash rollback, and retained-history updates. |
| [RenamedAnnotationSessionMigrator](../../src/labelimg/annotations/application/session.py) | Transactional migration of histories, targets, baselines, resource identities, and conflicts. |
| [FileRecoveryCenter](../../src/labelimg/files/application/recovery.py) | Bounded session log and recovery status transitions, without UI callbacks or inverse file logic. |
| [SystemTrashAdapter](../../src/labelimg/files/application/operations.py) | Opaque recovery identities or an explicit manual-trash result; the [Qt adapter](../../src/labelimg/files/infrastructure/qt_trash.py) supplies portable trash operations. |

`MainWindow` composes these owners and presents outcomes; it does not own inverse edits or move history cursors directly. At rest, the controller's immutable revision is the canonical annotation document and Canvas shapes are its projection. During a gesture, Canvas is a transient working copy: commit captures a revision, cancel restores the source. `SelectionSet` owns only transient selection. Saves build adapter documents from immutable revisions, never a timer-fired Canvas capture.

## Immutable history state

Snapshots retain image identity, dimensions and fingerprint; ordered box geometry, labels, difficult flags and session identities; and verified/questioned review state. They contain no image pixels, Qt objects, or file bytes. [The domain types](../../src/labelimg/annotations/domain/history.py) define the schema.

Box tuple order determines label-list order, drawing layers, and pointer-target tie-breaks. Session identities are allocated monotonically in one workspace and never serialized into annotation formats. Creation, duplicate, paste, and Copy Previous allocate each committed result once; Undo/Redo reuse that identity. `Shape.copy()` itself remains unowned.

Unchanged boxes share frozen states between revisions. Memory accounting counts uniquely retained objects rather than multiplying a document's logical size by its history length. A transition retains source/destination revisions and snapshots, action description, affected identities/count, optional old/new label text, and estimated byte cost. It stores no callback, widget pointer, or operation-specific inverse.

## History interface

The history owner exposes an immutable per-image view and owns edit and history-step tokens. Only one token may be open for one image; nested mutation is invalid.

Undo/Redo prepares a target, projects it, and only then commits the cursor. A failed projection restores the source and aborts the step without advancing the cursor; the entry remains available for explicit retry, and the UI reports the concrete action and error. Failure of both projections enters [degraded state](#degraded-state). Redo restores the captured completed document, without rereading clipboard/source data or rerunning geometry under later zoom or snapping settings.

## Edit transaction lifecycle

Every mutation follows one path:

1. Capture the complete pre-edit snapshot.
2. Start one edit transaction with an action description.
3. Apply the user's complete intention.
4. Cancel if the user cancels or the resulting annotation snapshot equals the source; create no transition, dirty change, or Redo clearing.
5. Allocate and retain the complete transition.
6. If editing, allocation, or recording fails, restore the pre-edit snapshot without recording a transition.
7. Commit the transition, clear only this image's Redo branch, refresh derived candidates, update menu/status state, and schedule saving if dirty.

Programmatic history projection, document load, workspace rebase, and file-operation rebase execute inside a projection guard. Widget signals emitted during the guard cannot begin edits.

### Operation boundaries

| Operation | Transaction start | Commit | Cancel/no-op |
| --- | --- | --- | --- |
| New box | first drawing point | valid geometry plus confirmed label, including default-label and single-class flows | label cancel or invalid geometry |
| Existing label/properties | dialog open or direct control activation | one accepted changed result | cancel or unchanged value |
| Left drag move/resize/edge/vertex | mouse press on a mutation target | mouse release | `Esc`, `Ctrl+Z`, lost mouse grab, or unchanged geometry |
| Arrow nudge | first accepted arrow press | all held arrow keys released or Canvas loses focus | no coordinate changed |
| Delete/duplicate/paste/copy previous | immediately before command | complete resulting scene | empty target or command failure |
| Current review state | before toggle | complete mutually exclusive review state | no change or mutation failure |

Arrow auto-repeat events mutate inside the same open nudge transaction. Pressing another arrow while one remains held stays in that transaction; release of the final held arrow commits it.

If a mouse gesture loses its grab before release, it is canceled because the user never committed it. If an arrow hold loses focus, its already-applied movement is committed once because canceling visible keyboard movement on focus change is more surprising than ending the gesture.

Copy Previous preserves the current observable command meaning: it replaces the current image's box set with copies of the previous image's current session document. If the previous image has retained in-memory state, that state is the source; otherwise its selected active stored document is loaded. An unresolved multi-format source must be selected first. The created result is captured once, so later source edits cannot affect Redo. The command retains its immediate save request, but that save is revision-bound and does not clear history.

Current-image review toggles likewise request an immediate save; other normal mutations follow the [autosave policy](#autosave).

## Canvas and workbench integration

Canvas reports gesture start, commit, and cancellation; per-move signals do not independently record history. Canvas retains immediate pre-gesture geometry, while the edit controller retains the complete pre-document snapshot for atomic recovery. Every box or current-image review mutation passes through the controller. Visibility, palette, selection, display options, and view controls do not dirty the document.

A successful baseline acknowledgement, explicit rebase, or workspace teardown can establish cleanliness. Loading, file-list refresh, and an attempted save cannot directly claim that edits were saved.

## Snapshot projection

Projection is a whole-scene operation:

1. Capture focus, zoom, pan, editing mode, filters, and visibility keyed by surviving session identity.
2. Block Canvas, label-list, difficult-button, and related widget mutation signals.
3. Rebuild shapes in exact snapshot order and rebuild the two label-list maps.
4. Preserve visibility for identities existing before and after; restored or new identities default visible.
5. Apply the result selection:
   - box action: exactly the surviving affected boxes;
   - one survivor: active;
   - multiple survivors: last in annotation order active;
   - no survivor: no active box;
   - non-box action: preserve selection and active box.
6. Scroll the label list only enough to reveal the active item without taking focus.
7. Clear Canvas and annotation-list hover state.
8. Restore focus, zoom, pan, modes, and filters.
9. Release signal guards and repaint once.

An exception at any step causes full projection of the source snapshot. Incremental best-effort projection is forbidden.

## Per-image history and workspace lifecycle

Histories are keyed by canonical absolute image path inside a workspace session.

- Navigating between images retains each history while it matches stored resources. Opening an image validates those resources and rebases a clean stale history to the latest valid document.
- Navigation first cancels any open Canvas/edit-controller transaction and restores its source snapshot. A destination is never selected while the source image still owns an edit or history-step token.
- Rename transactionally migrates histories, active-document choice, dirty state, conflicts, pending saves, selection paths, and current-image identity.
- Image deletion removes its in-memory history.
- Restoring a deleted image starts from the restored files as a new baseline with no old history.
- Explicit annotation-document replacement first resolves dirty changes and conflicts, then replaces current content and its active storage target and rebases that image; it does not merge boxes.
- Clear annotations and cross-file review edits rebase only successful targets.
- Opening another image directory, changing the annotation directory, or restarting ends the session and clears all histories.

An annotation-directory change preflights the new directory and current document before committing. On success, it loads the new directory's document for the current image or a clean empty baseline. On failure, every old-workspace state remains unchanged. Saving one image to another target does not redefine the workspace.

### Unsaved image-navigation guard

Every user-requested image switch first cancels pending work, then synchronously completes a safely queued autosave if one exists. A pending edit, conflict, degraded state, disabled autosave, or failed save prevents that flush from bypassing the guard. If committed changes remain dirty, Save, Discard, or Cancel resolves only the current image. Save failure or Cancel preserves the current image. Discard verifies the stored fingerprint, reloads the saved document, and rebases history; a mismatch enters conflict resolution and cannot be discarded silently.

This applies to previous/next, file-list opening, and other user-requested jumps. Automatic navigation after a confirmed destructive file operation is exempt. Workspace replacement and close use the all-dirty-image summary in [external conflicts](#external-conflicts).

## Multiple annotation formats

When more than one supported annotation document exists for an image:

- no format precedence is applied silently;
- the file list marks the image as awaiting document selection;
- unresolved files contribute no candidate labels;
- first access presents format, full path, and modification time;
- canceling the chooser cancels navigation and preserves the prior image, Canvas, history, and file-list multi-selection;
- the chosen document is active for the session and becomes the clean baseline;
- unchosen files remain untouched.

A shared CreateML collection is indexed by `(collection path, normalized complete image reference)`. Qualified relative and absolute references retain their path identity; only legacy basename-only records use basename matching. File operations change only the uniquely matched record and remove the collection file only when no records remain. A loaded record preserves its original reference on save, including when a document is rebuilt from annotation history: the workspace resolves the unique collection record before writing. Zero or multiple matching records are rejected rather than guessed or appended. Each unique record is a document choice for its image, candidate-label ambiguity is tracked per record, and collection conflicts count and associate every matching complete reference rather than collapsing same-basename records.

An externally appearing format never silently replaces the active representation; the application offers an explicit switch. Saving to another format makes the new target active for the current session and preserves the old file. A later session prompts again.

Format and path are storage-target state, not annotation history. Changing them makes the image save-required but `Ctrl+Z` never changes them.

## Dirty state and saved baselines

Each image retains:

- current annotation revision;
- current storage target;
- saved annotation revision identity;
- saved target;
- fingerprint of the physical resource version corresponding to that baseline;
- optional save request currently in flight.

Dirty is exact:

```text
current revision != saved revision
or current storage target != saved target
```

The saved revision may be older than the retained Undo window. Its identity and fingerprint remain independent from evictable history.

Annotation-resource fingerprints contain existence, byte length, nanosecond modification time, and SHA-256 of the complete annotation bytes. Image fingerprints contain existence, dimensions, byte length, modification time, and a streaming SHA-256 so replacement by a same-size image is still detected. An absent resource has an explicit sentinel fingerprint. Fingerprints are captured after successful load/write and checked again immediately before commit; path names alone are never treated as identity.

Load-time coordinate clamping is a deterministic clean in-memory representation paired with the original file fingerprint. It creates no history, dirty state, or automatic write. A later real edit and save may persist those normalized coordinates.

Saving binds to an immutable revision and target. Completion acknowledges only the exact version actually written. If the user edits or moves history while the write is active, the newer current version stays dirty and is queued for a later save.

A saved baseline identifies the in-memory revision corresponding to the stored document, even when format quantization or omitted in-memory details make a round-trip parse differ. Saving does not replace Canvas with a reparsed result or add a history entry; explicit reload may apply that representation and rebase history.

An empty document with no boxes or review flag follows its active format's storage policy, including absence of a Pascal VOC file. Undo/Redo and autosave may remove or recreate that file without creating a cross-file recovery entry.

Save failure never moves a baseline or clears history.

## Save coordination and atomic files

Resource keys are canonical physical identities:

- Pascal VOC: one XML path;
- YOLO: one annotation TXT path plus the shared `classes.txt` vocabulary path;
- CreateML: one shared JSON collection path.

Requests sharing any key serialize. Locks are acquired in sorted canonical-key order to prevent deadlock. The current GUI-thread implementation may execute synchronously, but requests and acknowledgements still use immutable revision identities so future asynchronous execution cannot corrupt baselines.

### Single file

Write a peer temporary file, flush it, then atomically replace the destination in one replacement step. The existing destination is never deliberately removed before replacement; a failed replacement leaves the old resource and baseline.

### YOLO multi-file transaction

Stage the TXT and any changed class vocabulary first. Preflight all fingerprints again immediately before commit. Copy rollback backups without first moving live destinations away, replace each destination, and acknowledge no baseline until all replacements succeed. If replacement fails, restore every already-replaced destination. A failed rollback marks the resource conflicted and prevents autosave.

YOLO candidate labels and class indices are different models:

- candidates show only classes currently used by committed boxes in the workspace;
- existing YOLO indices never reorder or disappear;
- a new index is reserved on first committed use;
- an unused reservation alone does not make an image dirty;
- a later YOLO save persists the stable vocabulary; an unwritten, unused reservation expires with the session when no stored annotation references it. Typing and canceling never reserves an index.

### CreateML collection transaction

The coordinator retains the last-known complete collection model and fingerprint. Waiting requests coalesce the latest revision per image, update one collection model, and atomically replace one JSON file. Unsaved labels replace only their matching record contribution. The entire batch succeeds or fails; no image baseline advances on failure.

Review state is stored by every active format: Pascal VOC uses its existing root attribute, YOLO uses a leading `# labelimg-review: verified|questioned|unreviewed` metadata comment, and CreateML stores `verified` and `questioned` on each image record. Readers ignore unrelated YOLO comments. Existing CreateML records without those keys retain the legacy rule that a non-empty record is verified.

## Autosave

Autosave starts enabled for each workspace editing session, may be disabled for that session, and survives ordinary image navigation. It writes to the annotation directory, or the image directory when none is selected, with a 200ms debounce.

- A new edit, Undo, or Redo invalidates an older pending request.
- Returning to the complete saved baseline cancels the pending write.
- Landing on another dirty state schedules its current immutable revision.
- Requests for one shared collection coalesce.
- A conflict pauses autosave for every dependent image.
- Degraded images cannot autosave.
- A pending drawing, drag, label confirmation, or history step blocks ordinary manual Save and Save As, storage-format changes, and the autosave timer. Navigation, an accepted batch-review command, explicit annotation-document loading, workspace switching, and close cancel that transaction back to its source snapshot before inspecting dirty state or writing another resource. Declining batch confirmation leaves the pending transaction untouched.

Autosave never reads a mutable live Canvas after it has been queued.

## Coordination with file operations

Cross-file operations acquire the same canonical resource leases as saving. They cannot race an active or queued save.

- Image deletion waits for active writes, cancels queued writes for successful targets, removes their histories, and never allows a stale save to recreate deleted annotation files. Per the approved product rule, deletion does not prompt about unsaved Canvas edits.
- Annotation clearing and batch review wait for active writes, cancel obsolete queued writes, execute against verified current resources, and rebase only successful targets. Successfully clearing a targeted current image also discards its unsaved annotation changes and leaves it open as unannotated.
- Synchronized rename drains active writes, transactionally changes physical paths, then migrates histories, active documents, dirty revisions, conflicts, and any still-valid pending save requests to the new canonical keys.
- Recovery operations take the same leases and run only after their complete preflight remains valid under lock.
- Delete and clear are atomic per logical image target: if recycling any matching annotation resource or the image itself fails, resources already recycled for that image are restored before the next target is attempted. A partial rollback retains only identities still available in trash and reports any secondary restoration failure; consumed identities never contaminate the residual recovery payload.
- Repeated rewrites of one shared CreateML collection in a multi-image operation coalesce to one logical recovery resource: the first original trash identity is paired with the final post-operation fingerprint.

The lock acquisition order is shared with normal save coordination, preventing deadlock between a save, rename, clear, and recovery attempt.

## External conflicts

Fingerprints are checked on explicit reload and immediately before every save commit. Current-document synchronization follows [ADR 0025](../adr/0025-synchronize-only-the-current-annotation-document.md):

- Watch the current image's active annotation resources and annotation directory. After a short stability delay, a valid external creation, modification, replacement, or deletion rebases a clean current document, clears its history, updates its saved baseline and candidates, and shows a non-blocking notification naming the resource.
- Invalid or transient external data preserves the last valid Canvas and candidate contribution, reports the path and parsing failure persistently, and remains eligible for retry. A clean image may be left in that state; reopening it while the resource is invalid cancels navigation and preserves the then-current image.
- Directory metadata changes update only affected inactive images' derived statuses and candidate contributions. They do not load inactive documents into Canvas, replace their histories, or trigger a full scan. Inactive documents validate when opened. A watched CreateML collection refreshes all candidate contributions but replaces only the current Canvas record.
- Application-authored saves and content-identical external rewrites do not reload Canvas, clear history, or show an external-change notification.
- A dirty current document enters conflict. Repeated external writes coalesce into one conflict against the latest stable valid external version. While drawing, geometry editing, or label confirmation is pending, resolution waits for that interaction to close and uses its committed result as the local version.

Conflict belongs to the physical resource: a per-image file affects one image, a CreateML collection affects every matched complete record reference, and a YOLO vocabulary conflict pauses every write sharing that vocabulary. Autosave conflict is non-modal; editing and history remain available, the file list keeps a conflict indication, and resource saves pause. An unresolved current conflict blocks image navigation.

| Choice | Result |
| --- | --- |
| Load external | Replace the retained resource model and rebase dependent histories, discarding their local edits. |
| Overwrite external | Immediately and atomically write the retained pre-conflict resource model plus current in-memory edits, discarding external changes; advance baselines only on success. |
| Cancel | Keep the conflict, in-memory content, history, and dirty state; autosave stays paused. |

CreateML resolution is collection-wide, with no per-record mixing. Discarding multiple images' local or external changes requires a second confirmation showing affected image count, dirty image count, and the side being discarded. Candidates use local committed contributions until resolution; unaffected records may use valid external contributions.

Close or workspace replacement first cancels pending work and drains active writes, then presents one summary for remaining dirty images and resource conflicts. Dirty rows require Save or fingerprint-verified Discard; conflict rows require the resolution choices above. Cancel or failure aborts the transition. Explicit apply-to-all is allowed for resource choices. Resources commit independently, so a later failure preserves completed resolutions and leaves only unresolved rows for the next attempt.

## Degraded state

If target projection and rollback projection both fail:

1. clear only the affected image's history;
2. attempt to load the fingerprint-verified stored document;
3. if successful, establish it as a clean rebase;
4. otherwise retain the last constructible in-memory snapshot as dirty and enter degraded state.

Degraded state:

- disables annotation creation and mutation;
- disables Undo, Redo, and autosave;
- allows view, selection, copying, reload, close, and rescue Save As;
- requires rescue Save As to a previously nonexistent path;
- establishes successful rescue output as a clean baseline with empty history and unlocks editing; failed rescue preserves degraded state;
- never overwrites the original or another existing annotation file.

## Shortcut and menu routing

The Edit menu starts with Undo …, Redo …, a separator, then existing edit actions.

Routing:

- Canvas, label list, and non-text MainWindow areas: annotation history.
- `QLineEdit`, `QTextEdit`, `QPlainTextEdit`, spin-box editors, and editable combo boxes: native widget history.
- File list and descendants: no annotation Undo or Redo.
- Modal dialogs: suspend MainWindow history shortcuts.

Implement routing with a `ShortcutOverride`/`KeyPress` event filter that classifies `QApplication.focusWidget()` before consuming the sequence. Do not register a window-wide QAction shortcut that can preempt native text editing. The menu action displays the standard key sequence but invokes the same controller command as the router.

`Ctrl+Z` cancels an unfinished drawing or geometry gesture before consulting history. That cancellation creates no Redo item and ends the key press without undoing the preceding committed edit. During a pending drawing or gesture, Redo is disabled and its shortcut gives a status message.

`Ctrl+Z`, `Ctrl+Y`, and `Ctrl+Shift+Z` consume auto-repeat without advancing history. There are no toolbar history buttons or history panel.

Menu text is derived from the next transition, for example:

- `Undo Delete 3 boxes`;
- `Redo Move box`;
- `Undo Change label: cat → dog`.

Long label values are escaped and elided in the menu; the status bar may show the full text. Unavailable actions are disabled. Attempting Undo past an evicted boundary gives a status explanation distinct from an image that never had history.

Persistent conflict and degraded indications follow the [file-list status contract](workspace-file-list.md#status-and-review). History availability alone has no file-list indicator.

## Candidate labels

The label-entry dialog's candidate area presents labels currently used by committed annotation boxes in the active workspace:

- include unambiguous unopened stored documents;
- include chosen active documents;
- include committed unsaved in-memory documents;
- retain those in-memory contributions across same-workspace rescans;
- use the in-memory side of an unresolved external conflict;
- exclude unresolved multi-format images;
- exclude typed-but-canceled, predefined-only, or previously-used-only labels.

For a shared CreateML collection, stored and unsaved contributions are keyed by `(collection path, complete normalized image reference)`. An unresolved format conflict excludes only the conflicting image record; the collection's other unambiguous records remain eligible. A rescan rebuilds disk-derived candidates but does not erase retained dirty-history contributions or session-reserved YOLO indices.

Undo of the final workspace use removes the candidate. Redo restores it. Ordering is `(label.casefold(), label)`, so case-only variants remain distinct and deterministic.

## File operation recovery center

The File menu opens `Recent File Operations…`. The center shows at most 20 entries, newest first. Any entry that passes current preflight may be recovered; recovery is not restricted to stack order. Each row has:

- operation type and time;
- successful target count;
- current status: recoverable, conflict, manual trash, restored, or unavailable;
- a Recover action when actionable.

Entries are session-only and cleared by workspace switch or application exit. Restored entries remain visible but cannot run twice.

Supported entries:

- image deletion: original image/annotation paths plus trash identities;
- annotation clearing: prior annotation resources plus post-clear fingerprints;
- synchronized rename: complete forward/inverse mapping;
- batch review change: prior and resulting review fields.

Recovery always performs whole-entry preflight. It never overwrites, invents suffixes, or silently restores a subset.

### Windows trash adapter

Use `IFileOperation` with `FOFX_RECYCLEONDELETE`, undo-record flags, and an item progress sink. `PostDeleteItem` returns `psiNewlyCreated`, the `IShellItem` representing the item in the Recycle Bin. The callback immediately copies its absolute PIDL bytes with `SHGetIDListFromObject`; it never retains the callback-owned COM pointer. Reconstruct an `IShellItem` from that PIDL when checking availability or using `IFileOperation.MoveItem` to restore it to the original parent/name after collision preflight.

The Windows adapter uses the `comtypes` dependency declared in [pyproject.toml](../../pyproject.toml). Do not parse private `$I`/`$R` files or guess by filename and deletion time.

Authoritative platform references:

- [IFileOperationProgressSink::PostDeleteItem](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperationprogresssink-postdeleteitem)
- [IFileOperation operation flags](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperation-setoperationflags)
- [SHGetIDListFromObject](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-shgetidlistfromobject)
- [comtypes package](https://pypi.org/project/comtypes/)

Before touching user data, Windows recycles and restores a same-directory probe of the same logical size. If the volume returns no newly created recycle item, or the PIDL cannot be reconstructed and restored, the adapter blocks the operation. It must not create an actionable recovery entry and no permanent-delete fallback is invoked by LabelImg.

### Other platforms

Use `QFile.moveToTrash` only when it succeeds. A nonempty returned trash path is an actionable identity. A successful trash operation with no usable returned identity creates a manual-trash entry after the agreed warning. If trash is unavailable, block deletion rather than permanently deleting.

## File recovery semantics

### Deleted images

- every original path must be unoccupied;
- every trash identity must still resolve;
- restore all or roll back all;
- refresh and naturally sort the file list;
- select every restored image;
- preserve the current image unless the workspace was empty;
- establish restored annotation documents as new clean baselines.

### Cleared annotations

- every target must still be empty as produced by the clear;
- any stored annotation or unsaved Canvas content blocks the entire entry;
- CreateML validates the complete post-clear collection fingerprint;
- recovery restores the exact prior documents as new baselines;
- no merge is offered.

### Rename

- validate a unique complete inverse mapping and unoccupied former paths;
- rename images and all annotation resources transactionally;
- preserve content edits made under new names;
- migrate current image, selection, history, active document, dirty state, and pending save identities;
- a successful inverse rename remains a new filesystem state, not byte rollback.

### Batch review

- every current review field must still equal the operation result;
- later box edits are preserved;
- later dirty candidate-label overrides are rebuilt after success or rollback;
- any later review change blocks the whole entry;
- restore prior review fields atomically;
- rebase affected annotation histories after success;
- preserve each image's selected active target and format; never force a Pascal VOC conversion;
- capture rollback bytes and verify current review fields while holding every affected resource lease;
- mark every attempted resource rollback-eligible before invoking its writer, so a commit followed by fingerprint or derived-index failure is still restored;
- roll back only resources attempted by the failed leased operation, so an external change made before lease acquisition is never overwritten;
- treat a missing empty Pascal VOC target as the valid empty-unreviewed operation result, allowing recovery to recreate a prior review-only document.

## Retention

- maximum 100 transitions per image;
- soft target approximately 256 MiB across the workspace;
- LRU is updated by history access, edit, Undo, or Redo, not by passive file-list painting;
- trim least-recently-used inactive histories first while retaining a contiguous window around each current cursor;
- remove the farthest Undo-side edge first, then the farthest Redo-side edge when no older Undo edge remains;
- never split one transition;
- preserve current snapshots and saved-baseline identities;
- permit one newest transition to exceed the soft target after all other history is evicted;
- if that transition cannot be allocated, fail and roll back the edit.

Eviction is silent until the user attempts to continue Undo beyond an evicted boundary. Redo transitions count toward the same limits. Eviction never moves a cursor to fabricate a clean state. Each history records whether an earlier Undo boundary was evicted so status feedback is accurate.

## Failure handling

Edit and no-op failures follow the [edit lifecycle](#edit-transaction-lifecycle); Undo/Redo failures follow the [history interface](#history-interface) and [degraded flow](#degraded-state). [Saved-baseline](#dirty-state-and-saved-baselines) and [external-conflict](#external-conflicts) rules govern persistence failures. The [recovery center](#file-operation-recovery-center) records successful targets only.

- File-operation rollback partial success: recovery payload records only resources whose trash identities remain available; already-restored resources are omitted.
- File recovery execution failure: roll back already restored/moved targets; if rollback fails, leave the entry conflicted and report every exact path.
- Post-commit cleanup failure: keep the operation successful and restored; stale backup cleanup is diagnostic detail, not evidence that the committed restore failed.

Every failure result is structured. UI code does not infer success from an absent exception alone.

## Non-goals

- persistent Undo/Redo across application restarts;
- a visual annotation history panel;
- arbitrary history-position jumping or preview;
- global `Ctrl+Z` for filesystem operations;
- automatic annotation or external-file merge;
- persistent recovery log across workspaces;
- recovering recycle-bin items after the application session ends;
- writing session annotation identities into annotation formats;
- silently choosing among multiple annotation formats;
- automatically deleting an old format after conversion.
