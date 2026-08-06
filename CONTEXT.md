# LabelImg Enhanced Context

This context defines the project identity and the language used for selecting and operating on annotation boxes in LabelImg.

## Language

**LabelImg Enhanced**:
The independently maintained derivative whose GitHub repository and Python distribution are named `labelimg-enhanced`, whose import package is `labelimg`, and whose application name and command remain `LabelImg` and `labelImg`. Its first independent release is version `1.9.0`, continuing from the upstream `v1.8.6` baseline.
_Avoid_: Upstream LabelImg, GitHub fork, `libs` distribution

**Application language**:
The user-selected language used for all visible LabelImg interface text. It is either Simplified Chinese or English, persists across launches, initially maps every `zh-*` system locale to Simplified Chinese and every other locale to English, and immediately updates the current application surface when changed without requiring a restart.
_Avoid_: Annotation language, label language, system-locale lock

**Interface text**:
Application-authored text visible during operation, including commands, panels, status and guidance, validation, confirmations, recovery, conflicts, and application-owned buttons. It excludes user-authored labels, file names and paths, annotation-format names, and verbatim operating-system diagnostics.
_Avoid_: User data, translated path, rewritten system error

**Image directory**:
The directory whose supported images form the current image-by-image annotation workspace. Opening another image directory replaces that workspace after unresolved changes are handled.
_Avoid_: Annotation directory, generic folder, implicit batch target

**Standalone file opening**:
Opening one image or annotation document directly without treating its containing directory as the current image directory. It is a secondary entry into the annotation workbench rather than the primary workspace-opening action.
_Avoid_: Open image directory, import directory, batch open

**Annotation directory**:
The directory that supplies and stores the active annotation documents for the current image directory. When no separate annotation directory is selected, the image directory serves this role. Switching it changes the annotation side of the workspace, reloads the current image's corresponding annotation document, and begins a new workspace editing session; it is not merely a passive save destination.
_Avoid_: Image directory, export directory, save-location-only setting

**Current annotation document replacement**:
The explicit replacement of the current image's annotation content and active storage target with a user-selected annotation document. It rebases annotation history and therefore requires unresolved edits to be handled before replacement; it is not an ordinary file-opening action.
_Avoid_: Open file, merge annotations, import additional boxes

**Image tool target set**:
The images explicitly chosen for one image-tool operation: either the image currently displayed on the Canvas or the images selected in the file list. A directory is never an implicit target set.
_Avoid_: Current directory, every image, inferred batch

**Image tool**:
A built-in LabelImg operation that transforms image pixels through an image processing session while leaving annotation documents unchanged. Every image tool uses an explicit image tool target set and the shared committed-image recovery model.
_Avoid_: Annotation tool, external script, optional plugin

**Colored frame overlay**:
A red or yellow rectangular outline added over image content and selected for removal by an image tool. Solid colored regions and ordinary red or yellow image content are not colored frame overlays.
_Avoid_: Every red pixel, every yellow region, colored object

**Colored frame repair region**:
The detected colored frame overlay plus only the bounded compression halo needed to remove its residual color. Pixels outside this region retain their color unless the user explicitly requests whole-image near-grayscale normalization.
_Avoid_: Whole image, every near-gray pixel, implicit grayscale conversion

**Image processing session**:
The temporary editing context in which one or more image-tool operations are composed and previewed before they replace image files. It owns its own image-processing Undo and Redo sequence, may coexist with unsaved annotations, and preserves annotation and Canvas view state; it cannot begin while an annotation gesture is pending.
_Avoid_: Annotation session, saved image, mixed history

**Image processing Undo**:
A request made while an image processing session is active to reverse its most recent uncommitted image-tool operation. Outside that context, Undo continues to target annotation edit history.
_Avoid_: Annotation Undo, committed-file recovery, global mixed Undo

**Committed image processing**:
An image-tool result that has replaced one or more source image files while retaining a recoverable original-file record. It is restored through image-processing recovery rather than annotation Undo or image processing Undo; one-click recovery lasts for the current workspace session, after which the original remains available only through the system trash.
_Avoid_: Preview, annotation edit, Ctrl+Z after commit

**Image processing batch commit**:
The all-or-nothing replacement of every image in one image tool target set after every result and original-file recovery path has passed preflight. A failure leaves every source image and annotation document unchanged.
_Avoid_: Partial batch, best-effort replacement, annotation rewrite

**Image processing recovery selection**:
The explicit subset of one committed image-processing batch chosen for restoration. The selected images restore atomically, while unselected processed images keep both their current result and their remaining recovery eligibility.
_Avoid_: Implicit file-list selection, mandatory whole-batch restore, partial selected restore

**Undo**:
A request to reverse the most recent reversible change in the applicable editing history.
_Avoid_: Recall, withdraw, rollback

**Redo**:
A request to reapply the most recently undone change while no newer reversible change has replaced that image's history branch. A new reversible annotation change discards only that image's redo branch; saving and view-state changes do not.
_Avoid_: Repeat command, restore from recycle bin

**Annotation edit history**:
The ordered reversible changes to one image's annotation document that are targeted by Undo and Redo. Each image retains its own history while the same annotation workspace remains open; the history does not contain file selection changes or cross-file operations.
_Avoid_: Application history, workspace history, file-operation log

**Annotation history snapshot**:
An immutable history state containing annotation boxes, stored properties, annotation order, review state, and session annotation identities. It shares only the current image's read-only identity and dimensions and never copies pixel buffers, so history retention accounts for annotation state rather than repeated image data.
_Avoid_: Canvas screenshot, copied image, serialized annotation file

**Annotation edit transaction**:
The single mutation boundary used by every user-committed annotation change. It captures the complete pre-edit snapshot, accepts one committed post-edit snapshot plus action metadata and affected identities, and either records the whole non-no-op transition or restores the pre-edit state. Nested annotation transactions are invalid.
_Avoid_: Direct `set_dirty`, per-event history write, partially recorded edit

**Pending annotation transaction**:
An annotation edit or prepared history step that has started but has not committed or canceled. It belongs to exactly one current image and blocks every ordinary manual save, including Save As, plus automatic saving and storage-format changes. Navigation, an accepted batch-review command, explicit annotation-document loading, workspace switching, and close cancel it back to its source snapshot before reading dirty state, selecting another document, or writing review fields. Declining a batch confirmation preserves the pending transaction unchanged. It is never silently abandoned or captured by a timer-fired save.
_Avoid_: Dirty Canvas, background gesture, transferable edit token

**History projection**:
The guarded replacement of the Canvas shapes, label-list rows, review state, and result selection from one annotation history snapshot. Projection blocks widget mutation signals, preserves eligible view state by session identity, clears stale hover state, and never creates another history entry.
_Avoid_: User edit, recursive history record, incremental best-effort rebuild

**Reversible annotation change**:
A user-committed change to the current image's annotation boxes, their stored properties, or its review state. Box creation, removal, duplication, paste, geometry adjustment, property editing, previous-image copying, and current-image review changes all qualify. Load-time geometry normalization is a deliberate non-history exception.
_Avoid_: View change, selection change, cross-file operation

**Atomic annotation edit**:
One complete user intention recorded as a single reversible annotation change. A drag gesture, review toggle, bulk operation, or one direction-key hold from press through release is atomic regardless of its internal event count or number of affected annotation boxes. Confirming an edit to an existing annotation records all label and property changes made through that confirmation as one entry; canceling it, or confirming without a content change, creates no entry. Candidate labels react only to the resulting committed annotation document. Redo restores the recorded completed document state rather than rerunning interaction algorithms; geometry therefore returns to its exact recorded coordinates regardless of later zoom, snapping, or view configuration.
_Avoid_: Mouse-move event, per-box batch entry, partial bulk undo

**History result selection**:
The view-state selection derived after Undo or Redo. For an entry that affects annotation boxes, the current selection is replaced by the affected boxes that exist in the resulting document; affected boxes removed by the result are absent, and unrelated prior selections are cleared. One surviving affected box becomes active; among multiple survivors, the last box in annotation order, and therefore the topmost drawing layer, becomes active; no survivor leaves no active box. The label list scrolls enough to reveal the active box but does not take keyboard focus, and canvas zoom and pan remain unchanged. For an entry such as a review-state change that affects no boxes, the current selection and active box remain unchanged. This feedback is not itself an annotation edit.
_Avoid_: Restored historical selection, selection history entry

**Session annotation identity**:
A stable identity assigned to an annotation box only for one workspace editing session, allowing history application to preserve view state for boxes that continue to exist without writing that identity into annotation documents. A create, paste, duplicate, or previous-image copy assigns each result a unique identity once, and every later Undo or Redo restoration of that result reuses it rather than generating another identity. Newly restored boxes use default view state.
_Avoid_: Persistent annotation ID, geometric matching, list-row identity

**Annotation order**:
The ordering of annotation boxes that determines label-list position, drawing layer, and the topmost tie-break in pointer target resolution. Undo and Redo restore this order exactly, including the relative positions of every box in a bulk edit.
_Avoid_: Unordered box set, append-on-restore, selection order

**View state**:
Transient interaction state such as selections, annotation visibility, zoom, pan, filters, editing modes, default drawing style, and canvas or annotation-list hover targets that does not alter an annotation document. View-state changes are not part of the annotation edit history and do not make the current annotation document dirty. A successful Undo or Redo clears any hovered box, vertex, edge, or annotation-list row because the scene or annotation order may have changed; hover is recomputed on later pointer movement without otherwise changing the result selection.
_Avoid_: Annotation content, reversible annotation change

**Default drawing style**:
The application preference used to initialize colors or appearance for future annotation boxes. Changing it affects neither existing annotation boxes nor their saved document and therefore creates no history entry and no save-required state; changing one existing box's line or fill color remains a reversible annotation change.
_Avoid_: Box color edit, annotation property, document dirty state

**Pending drawing**:
An annotation shape currently being drawn that has not yet become a valid annotation box. Undo cancels it before consulting the annotation edit history, and the canceled drawing cannot be redone. Redo is unavailable until the drawing is completed or canceled and does not modify the pending drawing.
_Avoid_: Created annotation, reversible annotation change

**Pending annotation gesture**:
A geometry-changing mouse gesture, such as moving, resizing, or dragging a vertex or edge, that has started but has not yet been committed by mouse release. Undo cancels the gesture, restores the complete geometry from mouse press, creates no Undo or Redo entry, and does not continue into the preceding committed history. Redo is unavailable until the gesture is committed or canceled and neither commits nor cancels it.
_Avoid_: Atomic annotation edit, live history entry, partial drag undo

**Load-time geometry normalization**:
The silent clamping of annotation coordinates to image bounds while a stored document is loaded. It is not an atomic annotation edit, creates no Undo or Redo entry, cannot be reversed through annotation history, and becomes the clean in-memory representation paired with the original stored-file fingerprint. It neither makes the image appear unsaved nor triggers a write by itself; a later real edit and save may persist the normalized coordinates, while a reload repeats the same normalization.
_Avoid_: Adjust-out-of-bounds history entry, user geometry edit, load confirmation

**Committed annotation creation**:
One atomic annotation edit formed only after a pending drawing has valid geometry and its label is confirmed, including default-label and single-class flows. Canceling label confirmation discards the pending drawing without creating history.
_Avoid_: Geometry-only creation, label-only creation, canceled annotation

**Workspace editing session**:
The period during which one image directory and one global annotation save directory remain open as a single annotation workspace. Switching among its images preserves their independent in-memory annotation edit histories. Opening another image directory, changing the global annotation save directory, or restarting LabelImg ends the session after unresolved dirty states and conflicts are handled; the newly scanned stored annotation documents become fresh baselines and all prior in-memory histories are cleared. A global save-directory switch is transactional: the new directory and current image document are preflighted before commit, and any scan or load failure leaves the original directory, canvas, candidate labels, and histories unchanged. After a successful switch, the current image immediately loads its corresponding document from the new directory, or a clean empty baseline when none exists; content from the old directory is never carried across as an unsaved canvas. Saving one image to a different target does not by itself redefine the whole workspace.
_Avoid_: Application lifetime, image visit, saved-file version

**Saved annotation baseline**:
The independently retained identity of the clean in-memory annotation revision corresponding to a stored document, paired with the annotation storage target and fingerprint of its physical representation. The in-memory representation may include deterministic load-time normalization or differ because a format quantizes geometry or omits in-memory-only details. The image is clean only when both its current in-memory revision and current storage target match this baseline. Saving never replaces the canvas with a round-tripped parse or creates a history entry; an explicit reload may apply that representation and then rebase history. Each manual or automatic save binds to the immutable document revision and storage target present when that write was requested; confirmed success moves the baseline only to the revision and target actually written, without clearing Undo or Redo. Writes are serialized by every physical storage resource they touch, including a shared CreateML collection, YOLO class vocabulary, or identical annotation path; only resource-disjoint writes may run concurrently. Requests arriving during an active write are coalesced into a follow-up write of the latest requested revisions. If editing, Undo, Redo, or a storage-target change has already moved the current state elsewhere, that current state remains dirty and a fresh autosave may be scheduled. A failed write leaves the prior baseline, dirty state, and history intact and reports the failure. Undo and Redo invalidate any previously scheduled autosave request so that a later write can consume only the then-current document state. Returning to the complete saved baseline cancels the unnecessary pending write; landing on a different dirty state schedules that current state instead. The baseline remains authoritative even when retention limits evict the history position that once represented it.
_Avoid_: History reset, undo boundary, application checkpoint

**Annotation storage resource**:
A physical file or shared metadata object touched by an annotation save, such as one Pascal VOC file, one YOLO annotation file plus its shared class vocabulary, or one CreateML collection. Save operations that share any resource are serialized under the same coordination boundary to prevent lost read-modify-write updates. Pending writes to one shared CreateML collection coalesce the latest requested revision for each affected image into one transactional collection update. The complete collection is written to a temporary file and atomically replaces the prior file; failure preserves the old collection and advances none of the included baselines. Only the exact revisions included in a fully successful batch advance their per-image saved baselines, while newer revisions wait for a later batch.
_Avoid_: Image-only save lock, independent CreateML record, uncoordinated classes file

**Annotation storage target**:
The annotation format and destination path selected for storing one image's current annotation document. Changing the target makes the image require saving but is not a reversible annotation change, so Undo and Redo neither switch formats nor change paths. A successful save updates the target paired with the saved annotation baseline without clearing annotation history. Saving to another format creates or updates that target and makes it the active annotation document for the session without deleting the prior format representation.
_Avoid_: Annotation content, Undoable format change, history branch

**Active annotation document**:
The one stored annotation representation selected as the baseline source for an image in the current workspace session. When multiple supported formats exist for the same image, the application does not silently apply format precedence: on first access it presents each format, path, and modification time for explicit selection, remembers that choice for the session, and leaves the unchosen files untouched. A successful save to another format makes the new representation active for the remainder of the session while preserving the old representation; a later session presents the resulting multi-format choice again. Canceling document selection cancels the entire image navigation, preserving the prior current image, canvas, history, and file-list multi-selection while the target remains unresolved.
_Avoid_: First-found document, merged formats, automatic conversion

**Empty annotation baseline**:
A successfully stored annotation state with no boxes and no retained review flag. The physical representation follows the active format's existing policy, including absence of a Pascal VOC file. Undo and Redo may move into or out of this state and autosave may remove or recreate the physical annotation file without creating a file-operation recovery entry.
_Avoid_: Missing-data error, explicit clear-annotations operation, file deletion recovery

**Discard unsaved changes**:
An explicit replacement of one image's in-memory annotation document with the externally verified stored document represented by its saved annotation baseline, followed by history rebase. If the stored document no longer matches the retained baseline fingerprint, the external annotation conflict flow applies before replacement. Discard cannot be undone or redone; canceling the discard prompt changes neither content nor history.
_Avoid_: Undo all, history navigation, temporary rollback

**History rebase**:
Replacement of an image's annotation edit history with a new baseline after a successful external document replacement or mutation, including explicitly loading another annotation document, annotation clearing, or cross-file review-state editing. Image renaming transfers the existing history to the renamed identity, while image deletion removes it.
_Avoid_: Undo, save, redo-branch discard

**External annotation conflict**:
A mismatch between an annotation storage resource on disk and the version underlying its in-memory annotation histories. An automatic save that detects a conflict pauses autosave for every image depending on that resource, preserves their current editing histories, and presents persistent non-modal warnings rather than interrupting an active drawing flow. For an independent per-image resource this affects one image. For a shared CreateML collection it marks every related image by matching each complete record reference, including qualified relative and absolute references, and conflict resolution targets the complete collection: loading the external version replaces the retained collection model and rebases every related image history, while overwriting applies current in-memory edits to the complete retained pre-conflict collection snapshot and atomically writes it, explicitly discarding every external collection change. Per-record mixing is unavailable. A collection-level resolution that discards multiple images' in-memory edits or external changes requires a second confirmation showing the total affected image count, dirty image count, and which side will be discarded; a single-image conflict uses only its normal conflict choice confirmation. The user may navigate away while those conflict, dirty-state, and history records remain retained and visibly marked in the file list. The conflict remains unresolved until an explicit save or reload requires a choice, and every conflict must be resolved before closing the workspace or application. Closing with multiple independent conflicts opens one summary in which each image or shared resource explicitly chooses rebase from the external version or overwrite with the in-memory version; no choice is preselected, although the user may explicitly apply one choice to all. Resolutions commit independently per resource: successful rows remain resolved if a later row fails, no cross-resource rollback is attempted, and the next attempt addresses only unresolved rows. The workspace closes only after every chosen resolution succeeds, and cancel or failure leaves it open. Conflicts are never silently merged, discarded, or overwritten.
_Avoid_: Live file watching, automatic merge, silent history reuse

**History retention limit**:
The bounded portion of a workspace editing session retained for Undo and Redo: at most 100 atomic edits per image and a soft target of approximately 256 MiB across the workspace. Least-recently-used inactive image histories are trimmed first while retaining a contiguous window around each current cursor: the farthest Undo-side edge is removed before a farthest Redo-side edge, and an atomic edit is never partially retained. If one newest atomic entry alone exceeds the soft target, it may remain as the sole retained entry after other history is evicted; failure to allocate that complete entry instead fails and rolls back the edit atomically. Eviction shortens only the reachable Undo or Redo window; it neither invents a new saved baseline nor makes dirty-state detection approximate. Cleanup is silent when it occurs, but attempting to continue Undo past an evicted boundary produces a non-modal status-bar explanation; an image that never had earlier history simply presents Undo as unavailable.
_Avoid_: Persistent archive, unlimited history, partial batch history

**Annotation history shortcut context**:
The focus context in which annotation Undo and Redo shortcuts apply: the canvas, label list, and non-text main-window areas. Text controls retain native text history, file-list focus performs no annotation history action, and modal dialogs suspend main-window history shortcuts. Ctrl+Z, Ctrl+Y, and Ctrl+Shift+Z ignore keyboard auto-repeat so that each physical key press advances exactly one history step; this does not alter direction-key hold coalescing.
_Avoid_: Application-wide shortcut, file-operation undo, text-field override

**History action presentation**:
The Edit-menu and status-bar representation of the next available annotation Undo or Redo, named after its concrete atomic edit and disabled when unavailable or outside the annotation history shortcut context. Action labels remain concise and include affected-box counts where useful. A label change presents safely rendered, elided old and new values such as `Undo Change label: cat → dog`, while the status bar may show the complete values; other actions use the operation and count rather than verbose payloads. Undo uses Ctrl+Z; Redo accepts Ctrl+Y and Ctrl+Shift+Z; the initial feature has no history panel, preview, or arbitrary multi-step jump. While a drawing or annotation gesture is pending, Redo is disabled and its shortcut only reports that the current operation must first be completed or canceled.
_Avoid_: Hidden unavailable action, unlabeled generic history button, toolbar history controls

**Atomic history execution**:
Application of one Undo or Redo that either completes and advances the history position or restores the complete pre-attempt state without advancing. When restoration succeeds after an application failure, the failed entry remains available for an explicit retry and the UI reports the concrete action and error; it is not silently discarded. A later new edit follows normal branch rules. If both application and restoration fail, only that image's history is cleared. The application first reloads a fingerprint-checked stored document as a clean new baseline; if no trustworthy stored document can be loaded, it retains the last constructible in-memory snapshot as dirty, pauses autosave, and requires an explicit Save As, reload, or close decision rather than claiming that uncertain state is saved.
_Avoid_: Partial undo, optimistic cursor advance, workspace-wide reset

**Degraded annotation state**:
The protected per-image state entered when neither a history action nor restoration of its pre-attempt snapshot can complete and no trustworthy stored document can be loaded. The last constructible in-memory document remains visible and dirty, annotation history and all annotation mutations are unavailable, and autosave is paused until explicit recovery. View operations, selection, copying, Save As, reload, and close remain available so the visible content can be inspected or rescued. Recovery Save As requires a previously nonexistent target and cannot overwrite another annotation file. Its success establishes the visible document as a clean baseline with empty new history, unlocks editing, and leaves the original file untouched; failure preserves the degraded state.
_Avoid_: Clean rebase, automatic overwrite, workspace-wide failure

**File operation recovery**:
A session-scoped recovery mechanism for successfully completed parts of cross-file deletion, annotation clearing, renaming, and review-state changes. Its newest-first list allows any entry that passes current preflight rather than enforcing stack order, uses explicit confirmation, and never uses annotation Undo or Redo shortcuts.
_Avoid_: Global Undo, annotation Redo

**File operation recovery entry**:
One recoverable file operation retained among the 20 most recent entries of a workspace editing session. It records only the successfully changed targets, becomes non-repeatable after successful recovery, and may outlive neither a workspace switch nor an application restart.
_Avoid_: Persistent audit log, annotation history entry, repeatable restore

**Recovered file selection**:
The file selection set produced after deleted images are restored: every restored image is selected while the current image remains unchanged, unless the workspace previously had no image to display. Restored images use their recovered documents as new annotation-history baselines.
_Avoid_: Automatic recovered-image navigation, old row restoration, deleted in-memory history

**File recovery conflict**:
Any occupied original path or changed target document that prevents a file operation recovery entry from being restored exactly. One conflict blocks the entire recovery until resolved; recovery never overwrites, assigns conflict suffixes, or restores only a subset automatically, while rename recovery may carry later content edits through its inverse mapping.
_Avoid_: Best-effort restore, overwrite confirmation, automatic conflict suffix

**Rename recovery**:
An inverse synchronized rename that returns images, associated annotation documents, current-image identity, file selection, and annotation edit histories to their former paths while preserving content edited under the newer names. It requires a complete unique reverse mapping and unoccupied former paths.
_Avoid_: Old-byte restoration, content rollback, partial reverse rename

**Review-state recovery**:
A field-level reversal of one cross-file review-state operation that preserves later annotation-box content and its dirty candidate-label contribution. After acquiring every affected storage-resource lease, recovery reloads every record and verifies that its current fields still equal the operation result before capturing rollback bytes or writing. An absent empty Pascal VOC document is the valid physical representation of empty and unreviewed, so it can be restored to a prior review-only document. Every attempted resource is rollback-eligible even when its writer commits and post-commit fingerprinting or derived-index bookkeeping then raises. Successful recovery restores the prior states atomically and rebases the affected annotation edit histories.
_Avoid_: Whole-document restoration, box rollback, partial review recovery

**Cleared-annotation recovery**:
Exact restoration of annotation documents removed by one clear operation, allowed only while every target remains in the empty annotation state produced by that operation. New stored annotations or unsaved canvas annotations create a conflict; old and new annotations are never overwritten or merged automatically.
_Avoid_: Annotation merge, overwrite restore, partial clear recovery

**Manual trash recovery**:
The fallback for a platform that can move data to its system trash but cannot return a stable recovery identity. The destructive operation remains allowed with an explicit warning, but its recovery entry is non-actionable in LabelImg; permanent deletion is never used when system trash is unavailable.
_Avoid_: Application recovery, permanent-delete fallback, silent degradation

**Trash recovery identity**:
An opaque session-scoped handle returned by the platform trash adapter for one successfully recycled path. On Windows, `IFileOperationProgressSink::PostDeleteItem` reports a callback-owned Recycle Bin `IShellItem`; the adapter immediately copies its absolute PIDL bytes and later reconstructs a fresh item for availability checks and restore. A same-directory recycle-and-restore probe must succeed before user data is touched. On platforms where Qt returns a usable path in trash, that path forms the identity. The application never retains a callback-owned COM pointer or derives identities by matching only names or deletion timestamps.
_Avoid_: Original path, filename search, guessed recycle-bin path

**Temporary multi-selection mode**:
A transient canvas state entered while Ctrl is held, shown with a crosshair cursor, in which a click toggles one annotation box and a drag creates a selection region without moving an annotation box. It retains the complete-box hover target appearance but suppresses corner enlargement and resize cursors; releasing Ctrl restores ordinary editing feedback, ends the mode, and preserves the selection set.
_Avoid_: Square-drawing mode, generic selection mode

**Selection region**:
A dashed, lightly translucent rectangle drawn during temporary multi-selection mode that selects only annotation boxes fully contained within its bounds. Once its drag threshold is crossed it suppresses any single-box hover target, and release recomputes hover at the pointer position.
_Avoid_: Intersection region, crop box, annotation box

**Selection set**:
The zero or more annotation boxes currently selected as a group and mirrored between the canvas and label list. A new selection region replaces this set; Ctrl-click toggles individual members.
_Avoid_: Active box, current item

**Bulk selection action**:
An action whose target is every annotation box in the selection set. Bulk selection actions are limited to deletion and copying; other edits require a single selected box.
_Avoid_: Batch edit, group transform

**In-image duplication**:
A copy operation that creates slightly offset annotation boxes in the current image from every member of the selection set. The duplicates replace the originals as the selection set.
_Avoid_: Clipboard copy, paste

**Clipboard selection**:
A snapshot of every annotation box in the selection set, retained for pasting into another image. Paste history captures the boxes actually created, so Undo does not change the clipboard and Redo never rereads it.
_Avoid_: In-image duplication, all image labels

**Previous-image annotation copy**:
An atomic annotation edit that replaces the current image's box set with copies from the previous image's current session document, or its selected active stored document when no in-memory state exists. Its history entry retains the boxes actually created, including their properties and annotation order, so Redo restores that captured result without rereading the source image. Later edits, renames, or deletion of the source image cannot change the result.
_Avoid_: Live link, source-dependent Redo, clipboard paste

**Append paste**:
A paste operation that adds the clipboard selection to the target image without removing its existing annotation boxes. The newly pasted boxes replace the prior selection set.
_Avoid_: Replace paste, overwrite labels

**Selected appearance**:
The visual state of a selected annotation box: an opaque outline in its own label color and a light translucent fill in the same color at 30/255 opacity. Hover feedback does not fill an unselected box, so it remains distinct from selection.
_Avoid_: Default blue fill, white selection outline

**Label display color**:
The opaque color derived from a label's text and shared by annotation-box outlines, candidate-label capsule backgrounds, and right annotation-list row backgrounds. Selection fill, text colors, and hover borders are separate appearances.
_Avoid_: Per-surface label color, translucent label background, selection color

**Selected label text appearance**:
The visual state of label text belonging to every selected annotation box: white text on a black background at about 60% opacity, with a small rounded rectangle and about two pixels of padding around the text. It remains at the annotation box's existing top-left position. Hovering without selection does not apply this appearance, and hidden label text remains hidden.
_Avoid_: Label-list highlight, active-box-only label, hover label highlight

**Hover target appearance**:
The edit-mode preview of the one annotation box targeted by the pointer: its ordinary solid outline is replaced by a short-dashed outline with clearly separated, roughly equal dash and gap lengths, the same approximately 1.5-pixel width, and its own label color, without an underlay, added fill, or label-text change; creation mode never shows it. It outlines the complete box for corner, edge, and interior targets and remains on a locked gesture target, while existing corner enlargement, resize cursors, and selected-box appearance remain intact.
_Avoid_: Hover fill, hover label highlight, thick hover outline, white hover underlay

**Corner resize target**:
The interactive area at an annotation-box corner that resizes the box along the corner's geometric diagonal. It contracts for very small boxes so that a distinct box-move target remains available.
_Avoid_: Fixed-radius corner target, entire small-box interior

**Box-move target**:
The annotation-box interior that remains after corner and edge resize targets are resolved and moves the whole box when dragged.
_Avoid_: Corner resize target, edge resize target

**Pointer target resolution**:
The deterministic choice of the nearest visible annotation target at the pointer: nearest eligible corner first, then nearest eligible edge, then the overlap target among containing box-move targets. It depends only on current geometry and pointer position, never current selection membership; distances inside a small equality tolerance resolve to the topmost drawing layer rather than using hover stickiness or approach direction.
_Avoid_: Drawing-order scan, first hit, stateful selection-through

**Label text placement**:
The label text position separated from the annotation-box outline, normally above its top-left corner and moved inside the box when the canvas boundary leaves insufficient space above.
_Avoid_: Text baseline on the outline, clipped label text

**Overlap candidates**:
The visible annotation boxes whose box-move targets contain the pointer after corner and edge resize targets are resolved. Hidden boxes and boxes that do not contain the pointer never participate in overlap targeting.
_Avoid_: Nearby boxes, hidden candidates, stateful selection-through

**Overlap target**:
The overlap candidate previewed by hover and targeted by an ensuing ordinary click, Ctrl-click, or right-button gesture; modifier keys never change this target. Strict containment chooses the innermost smallest-area candidate, partial overlap chooses the candidate whose boundary is nearest to the pointer, and unresolved geometric equality chooses the topmost drawing layer while lower identical boxes remain selectable from the annotation list.
_Avoid_: Nearest center, drawing-order-only target, stateful selection-through

**Pointer gesture target**:
The annotation box recomputed at mouse press and retained for that click or drag until release or cancellation. Hover only previews this target; its complete-box highlight remains fixed during the open gesture, and crossing another box never retargets it.
_Avoid_: Cached hover target, mid-drag retargeting

**Synchronized selection**:
A selection set projected between canvas boxes, annotation-instance buttons, and their label-group rows. An ordinary instance-button click selects only its box, while an ordinary click on the group-row body selects every box in the group; Shift ranges follow one global visual order across groups, reading rows top-to-bottom and buttons left-to-right, regardless of horizontal scroll position. A single box is a point anchor, while a group selection is an interval anchor that remains complete when a later Shift range extends before or after it. A multi-member group selection has no arbitrary active box and disables single-instance editing, while a one-member group remains a single selection. Each row reports none, partial, or all according to the resulting selection set.
_Avoid_: Current row, independent list selection, one-row-one-box

**Label group**:
The annotation boxes in the current image that share exactly the same label, including letter case. A label group exists only while at least one matching box exists.
_Avoid_: Dataset class, case-insensitive class, persistent group

**Label-group row**:
The single compact, theme-background right annotation-list row representing one label group, ordered by case-insensitive natural label order with exact text as the stable tie-breaker. Visible rows share a generous but bounded, content-fitted class-name column sized for its bold selected appearance, so selection never newly elides a name or shifts instance buttons; long names may claim nearly half the row while at least one button remains complete, and any necessary elision is identical across selection states with full hover identification.
_Avoid_: Annotation row, instance row, category row

**Annotation-instance button**:
The compact numbered in-row control representing exactly one annotation box within its label group, with an opaque background matching that box's actual outline color. Every group member has a button in current annotation-document order; ordinary click selects only that box, hover previews only that box, and its tooltip identifies the current ordinal and box geometry. Ordinals are current-image navigation aids that may be renumbered after structural edits, not persisted annotation identities.
_Avoid_: Group button, count badge, hidden overflow item

**Annotation-instance button appearance**:
The theme-background button with an outline matching that box's actual annotation color and a readable theme-colored number. Neither the row nor an unselected button uses category-color fill; selection adds a modest 48/255 fill in the same color plus a bold number, while hover independently changes the color outline from solid to dashed so a selected-hovered button retains both states; a hidden button dims its outline and number to roughly 45% and adds a fine slash.
_Avoid_: Category-color fill, label-group-only color, additional hover outline, state-overwrites-category-color

**Annotation-instance strip**:
The independently horizontally scrollable portion of a label-group row containing every annotation-instance button while the label identity, total count, and aggregate visibility control remain fixed. Ordinary wheel input continues to scroll the list vertically, deliberate horizontal input moves the strip, and canvas selection minimally reveals its matching button without hover-driven movement; canvas hover over an off-strip instance instead emphasizes the corresponding overflow direction until explicitly revealed. Strip positions survive view changes within the current image, reset on image change, and are never persisted as annotation or workspace data.
_Avoid_: Wrapped button grid, clipped instance list, whole-row scrolling

**Annotation-list keyboard navigation**:
The focus model in which Tab reaches the label-group list without traversing every instance, arrows move between group rows and their visually ordered instance buttons, and Space performs the corresponding selection gesture. Escape returns from an instance to its group, F2 edits at the focused granularity, and keyboard focus movement reveals controls without creating hover state.
_Avoid_: Button-by-button tab chain, mouse-only strip, focus-is-selection

**Label-group rename**:
An atomic label edit applied to every annotation box in one label group. Renaming to an existing label merges the groups, while an instance-only label edit moves its annotation-instance button between groups and removes an emptied source group.
_Avoid_: Row-title-only edit, repeated independent rename, persistent empty group

**Label-group filter**:
A case-insensitive text filter that limits which label-group rows are shown without changing canvas visibility, annotation selection, or row state. Selection outside the result remains active and is reported explicitly; list-focused select-all replaces it with all currently filtered results. Clearing the filter restores every group and its prior horizontal position.
_Avoid_: Visibility filter, label isolation, selection filter

**Annotation-list empty state**:
The non-interactive explanation shown after projection when the current image has no annotations, distinct from the no-match state produced by a label-group filter. A no-match state offers filter clearing and continues to report selected annotations outside the result without changing canvas state.
_Avoid_: Blank list, disabled placeholder row, transient rebuild flash

**Annotation-list summary**:
The compact current-image count of label groups and annotation boxes near the label-group filter. During filtering it reports shown and total counts and any selected annotations outside the result, without including workspace candidate labels.
_Avoid_: Workspace class count, dashboard card, hidden-selection silence

**Label-group isolation**:
An explicit group command that hides other label groups on the canvas, distinct from filtering rows. Its inverse restores visibility to every group.
_Avoid_: Search, implicit combo-box visibility, list-only filter

**Annotation-list command scope**:
The explicit target of a context command: right-clicking an unselected instance makes it the selection target, right-clicking a selected instance preserves the selection set, and right-clicking a group body preserves selection while targeting the named group. Group-destructive commands state their affected annotation count.
_Avoid_: Implicit group selection, ambiguous current item, unlabeled bulk scope

**Label-group deletion**:
An atomic, undoable removal of every annotation box in one label group, identified before execution by the group label and affected count. It does not require modal confirmation because one Undo restores the complete group state.
_Avoid_: Repeated instance deletion, irreversible bulk delete, confirmation dialog

**Synchronized hover**:
A view-only projection between canvas boxes and label-group rows at the granularity of its source. Hovering one canvas box previews only that box and its group row; hovering a group row previews every visible box in the group. It never changes selection, visibility, scrolling, dirty state, or annotation history, and hidden boxes remain absent from the canvas.
_Avoid_: Hover selection, current row, one-way hover, reveal hidden boxes

**Label-group hover preview**:
The simultaneous ordinary hover outline shown on every visible annotation box belonging to a hovered label-group row. It represents the row's group-wide scope without creating a multi-selection or replacing the canvas pointer target.
_Avoid_: Group selection, hidden-box preview, single representative box

**Selected label-list appearance**:
The aggregate selection state of a label-group row with its label background preserved. No selected members show no marker and normal text; some selected members show a small theme-accent dot and normal text; all selected members show the existing slim inset theme-accent marker and bold text.
_Avoid_: Full blue border, primary row, active-row emphasis, binary group selection

**Annotation-list hover appearance**:
The view-only treatment of the complete annotation-list row in synchronized hover, including its visibility-control area: the same faint theme-gray background used by the file list plus an approximately one-pixel neutral-gray rounded border inset from the row bounds. A selected hovered row retains its selection marker and bold text, while instance buttons keep their own selection and category-color states.
_Avoid_: Category-color hover background, blue border, bold hover text

**Initial image selection**:
The empty selection set established whenever an image becomes current, regardless of whether it was opened directly, reached by navigation, chosen from the file list, or revealed after deletion.
_Avoid_: Last-label selection, carried selection

**Visibility toggle**:
The right-aligned label-group eye control that changes whether the group's annotation boxes are rendered on the canvas without changing the selection set. Open-eye and subdued eye-off states mean all visible and all hidden; a distinct mixed state means only some are visible. Activating an all-visible group hides it, while activating an all-hidden or mixed group shows it completely; instance-button commands control individual or selected-box visibility without adding miniature eyes. Hidden boxes cannot be hit on the canvas but remain in their strips and eligible for selection actions.
_Avoid_: Selection checkbox, disabled row, miniature instance eye

**Label**:
The object-class name assigned to an annotation box.
_Avoid_: Tag, category text

**Candidate label**:
A label derived from the classes currently used by committed annotation boxes anywhere in the open workspace and offered for reuse while creating or editing a box. Its scope includes unambiguous stored annotations for images that have not yet been opened, selected active annotation documents, and committed but not-yet-saved annotations in memory. A workspace rescan rebuilds stored contributions without clearing retained dirty-history contributions. An image with multiple formats and no selected active document contributes no candidates and remains visibly marked as awaiting document selection. A conflicted image contributes its current in-memory labels until conflict resolution: rebasing to the external document replaces its contribution, while overwriting preserves it. Candidates retain the existing case-insensitive alphabetical ordering, with the exact original label text as a deterministic secondary key. Labels that differ only by letter case remain distinct annotation classes and are never merged or renamed by Undo or Redo. Undo and Redo recompute membership without introducing operation-order sorting: if Undo removes the last committed use of a class across the whole scope, that class disappears; Redo makes it reappear at its deterministic sorted position. Merely typing, previously using, or predefining a label does not keep it in the candidate set when no committed annotation currently uses it.
_Avoid_: Session label history, predefined class list, option, list item, tag

**YOLO class index vocabulary**:
The storage metadata that maps YOLO class names to stable numeric indices. It is independent of the visible candidate-label set. A new class appends an index when its first annotation is confirmed as a committed edit; typing and canceling does not reserve one. Once appended, the mapping remains stable across workspace rescans and later YOLO saves even if Undo removes every current box of that class. A reservation that has never been written and is no longer used does not by itself make an image dirty or force a save; it is persisted opportunistically by a later YOLO save or expires with the session when no stored annotation references it. Undo and Redo never remove, reorder, or renumber an established mapping when the class disappears from candidate labels.
_Avoid_: Candidate labels, sorted class list, compacted indices

**Candidate area**:
The portion of the label-entry dialog that presents candidate labels.
_Avoid_: Candidate frame, label list

**Annotation document**:
The annotation boxes and review status associated with one image, whether stored as Pascal VOC, YOLO, or CreateML.
_Avoid_: Label file, format file

**CreateML annotation collection**:
A physical CreateML JSON file that may contain annotation-document records for multiple images. Each record is identified by the collection path plus its complete normalized image reference for document choice, review state, and candidate-label derivation; a qualified relative or absolute reference is never collapsed to a basename, while a legacy basename-only reference retains basename matching. A matching record keeps its original reference when saved, and zero or multiple matches are rejected instead of appending or selecting a guessed record. The collection file remains the physical save/conflict resource. File operations target the uniquely matching image record and remove the physical collection only when no records remain; one multi-image operation records one logical recovery resource per collection, retaining the earliest original trash identity and the final post-operation fingerprint. Recovery restores the complete prior collection only while that final state remains unchanged. Ambiguity or an unsaved override for one record does not suppress or replace unrelated record contributions.
_Avoid_: Single-image JSON document, delete-whole-file-by-default

**Annotation workspace**:
The images being annotated together with their corresponding annotation documents and the candidate labels discovered from them.
_Avoid_: Image folder, save directory, dataset

**File-list display path**:
The image path shown in the file list relative to the opened annotation-workspace root. The root itself is omitted while nested folders remain visible; the full absolute path remains the image identity and is available on hover.
_Avoid_: Absolute-path label, basename-only flattening

**File-list view order**:
The complete workspace-image sequence produced by the chosen file-name, image-modification-time, annotation-state, or review-state ordering and direction. Relative directories remain natural-order batches, filenames are naturally ordered within each batch, and this stable sequence governs rows, visible-image navigation, and ordered batch commands.
_Avoid_: Base-name-first order, visual-only sort, unstable status order

**File-list filter**:
A conjunctive view of workspace images by display-path text, annotation state, review state, and persistence-alert presence. It changes row visibility without changing the current image or retained file selection, explicitly reports hidden current and selected images, and scopes later selection-building commands to visible results.
_Avoid_: File selection, image navigation, destructive scope

**Filtered file navigation**:
The non-wrapping previous/next sequence of visible images in file-list view order. A current image excluded by the filter remains open until navigation moves to the nearest visible image in the requested direction.
_Avoid_: Full-workspace navigation, wraparound navigation, automatic current-image replacement

**File selection set**:
The zero or more image files intentionally selected in the file list, independently of the current image and retained when filters hide members. An ordinary click replaces the set immediately, Ctrl-click toggles one member, Shift-click selects a contiguous visible range, Ctrl+A replaces the set with every visible file while the file list has focus, and clicking empty list space clears the set; other explicit selection-building commands likewise replace it from visible results. During the system double-click interval, the prior set may retain only its blue appearance so the first half of a double-click never flashes it as unselected; file commands and the selection count already target the newly clicked file.
_Avoid_: Current image, opened file, annotation-box selection set

**Selected file appearance**:
The persistent light theme-accent background shown across every row in the file selection set, without a leading accent block. It remains visible when another image becomes current and after keyboard focus returns to the canvas.
_Avoid_: Leading blue block, focus-only selection, current-image highlight

**File hover appearance**:
The theme-adaptive neutral-gray row background shown only while the pointer rests on an unselected file. It does not replace or overlay the selected-file appearance, current-image emphasis, or keyboard-focus indicator.
_Avoid_: Blue hover background, gray selected-file overlay

**Current image**:
The single image currently loaded for viewing and annotation. It is visually identified independently of the file selection set; opening or navigating to another image does not add, remove, or otherwise change selected files.
_Avoid_: Selected file, active selection

**File selection context**:
The file selection set targeted by a file-list context menu. Right-clicking a selected file preserves the existing set, while right-clicking an unselected file replaces the set with that file before opening the menu.
_Avoid_: Right-clicked file only, current image

**Image review state**:
The mutually exclusive review classification of an image's annotation document: unreviewed, verified, or questioned. A file-selection-context command sets every targeted image to one explicit state instead of toggling each image's prior state.
_Avoid_: Independent verified and questioned flags, mixed-state toggle

**Review-state representation**:
The format-specific persistence of image review state in the selected active annotation target: the existing Pascal VOC root attribute, one leading YOLO `# labelimg-review:` metadata comment, or per-image `verified` and `questioned` fields in CreateML. Batch review and recovery preserve the active format. A legacy CreateML record without explicit fields remains verified when it contains annotations.
_Avoid_: Pascal-only review file, format conversion, collection-wide CreateML flag

**File annotation state**:
The binary presence of annotation boxes for an image, independent of image review state. An annotated image shows a hollow bounding-box indicator in the first file-list status column, while an unannotated image leaves it empty; file selection by annotation state uses this same distinction.
_Avoid_: Combined progress category, review state, file-system status

**File-list status columns**:
The two compact, fixed leading columns before every file name: annotation presence first and image review state second. Their indicators are read-only row metadata: default states leave a centered slot empty without collapsing it, while clicks retain ordinary file selection and opening behavior and state changes remain explicit commands elsewhere.
_Avoid_: File-name suffix, variable leading badges, combined status column

**File-list state selection**:
A file-selection command scoped to exactly one independent status dimension: annotation selection distinguishes annotated from unannotated regardless of review, while review selection distinguishes unreviewed, questioned, and verified regardless of annotation presence. Each command replaces the current file selection set with all matching files.
_Avoid_: Combined progress-state selection, cross-dimension implicit filter, additive status selection

**File-list review indicator**:
The outline indicator in the second file-list status column: empty for unreviewed, an amber circled question mark for questioned, and a green circled check for verified. Shape and color both carry the non-default state, with the full review name available on hover.
_Avoid_: Binary verification dot, review suffix, color-only indicator

**File-list persistence alert**:
The fixed trailing file-list indicator reserved for unsaved, conflicting, ambiguous, or degraded annotation persistence state, prioritized in that severity order from degraded through dirty. Its distinct warning shape shows only the highest-priority active alert while hover identification lists every active condition, leaving the file-name text as the unmodified display path.
_Avoid_: File-name suffix, multiple trailing symbols, annotation progress state

**Recoverable image deletion**:
Removal of one current image or every image in a file selection context by moving each image and all matching Pascal VOC, YOLO, and CreateML annotation documents from both workspace annotation locations to the system recycle bin. Each image and its matching documents are one logical target: failure to recycle any member restores members already moved for that image before later targets continue. If that rollback is only partly successful, the recovery payload retains only identities that remain available in trash; already-consumed identities are never carried forward to block the residual recovery. Deletion does not preserve or separately prompt for unsaved changes to a targeted current image.
_Avoid_: Permanent deletion, image-only deletion, active-format-only cleanup

**Recoverable annotation clearing**:
Removal of all Pascal VOC, YOLO, and CreateML annotation documents associated with every image in a file selection context by moving the documents to the system recycle bin while preserving the images. The matching documents for one image are one logical target and are restored if any recycle move for that target fails. Shared CreateML rewrites from multiple selected images coalesce to one logical recovery resource with the original collection identity and final fingerprint. If rollback is only partly successful, only resources still available in trash remain recoverable. Clearing a targeted current image also discards its unsaved annotation changes and leaves it open as unannotated.
_Avoid_: Image deletion, active-format clearing, hiding annotations

**Synchronized image rename**:
A rename that preserves an image's directory and extension while changing its base name together with all matching annotation-document names and embedded image references. The renamed identity remains the current image or a member of the file selection set when it held that role before the rename.
_Avoid_: Rename image only, move image, convert image

**Batch rename plan**:
A previewed, conflict-free mapping from a file selection context to synchronized image renames. Names are generated in the pre-rename file-list order from a shared prefix, a template containing original-name or sequence tokens, a shared suffix, and the unchanged extension; the plan succeeds as a whole or is rolled back.
_Avoid_: Sequential rename prompts, partial batch rename, automatic conflict suffix
