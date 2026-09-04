# LabelImg Enhanced Context

The shared domain language for annotation workspaces, editing, and recovery. UI controls and appearance are defined in the linked feature designs; [docs](docs/README.md) indexes those contracts and decision history.

## Language

### Project and updates

Application and release behavior: [updates](docs/design/application-updates.md).

**LabelImg Enhanced**:
The independently maintained derivative of upstream LabelImg v1.8.6, distributed as labelimg-enhanced and presented to users as LabelImg.
_Avoid_: Upstream LabelImg, GitHub fork

**GitHub release**:
The canonical public distribution record for one LabelImg Enhanced version, with its downloadable assets and provenance.
_Avoid_: PyPI release, tag-only version

**Stable update check**:
A read-only comparison of the running version with the latest published stable GitHub release.
_Avoid_: Silent updater, prerelease channel

**Update center**:
The independent application window that presents the complete update lifecycle without blocking annotation work.
_Avoid_: Owned dialog, modal alert sequence

**Distribution strategy**:
The application-replacement ownership of a Python, portable frozen, or managed Windows installation.
_Avoid_: Operating system, package format

**Managed Windows installation**:
The current-user Windows application installed and maintained by the project's unsigned installer.
_Avoid_: Portable archive, pip environment

**Update package**:
The Windows installer and its matching release checksum entry; integrity verification does not establish publisher identity.
_Avoid_: Signed installer, wheel

**Downloaded candidate**:
A verified update package retained for an explicit installation request, not yet installed.
_Avoid_: Installed version, trusted publisher

**Update rollback**:
Restoration of the prior installed files when the installation transaction fails before completion.
_Avoid_: Post-launch health recovery, session restore

### Interface and Canvas navigation

Interaction details: [command surfaces](docs/design/canvas-tool-rail.md), [language](docs/design/bilingual-interface.md), [menus](docs/design/menu-information-architecture.md), and [icons](docs/icon-design-system.md).

**Application language**:
The user-selected Simplified Chinese or English language of the interface, independent of annotation labels and file content.
_Avoid_: Annotation language, label language

**Interface text**:
Application-authored visible text, excluding user labels, filenames, paths, format names, and verbatim operating-system diagnostics.
_Avoid_: User data, translated path

**Selection and editing tool**:
The default Canvas tool combining annotation selection, geometry editing, and property editing.
_Avoid_: Separate selection mode, separate editing mode

**Canvas pan mode**:
The Canvas mode in which dragging moves the viewport without selecting or moving annotation boxes.
_Avoid_: Blank-area-only pan, annotation move

**Image pointer coordinates**:
The zero-based original-image pixel indices beneath the pointer, available only inside the rendered image.
_Avoid_: Canvas-widget coordinates, image-edge geometry

**Annotation size readout**:
The width and height of the actual annotation rectangle, including active geometry constraints.
_Avoid_: Raw pointer displacement, pointer coordinates

**Canvas zoom percentage**:
The view scale at which 100% maps one image pixel to one logical screen pixel.
_Avoid_: Fit-relative percentage, image resize percentage

**Cursor-anchored zoom**:
A scale change preserving the image point beneath the pointer at the same viewport position, using the nearest image boundary outside the image.
_Avoid_: Scroll-range-proportional zoom, viewport-centered zoom

**Canvas wheel navigation**:
Wheel-based vertical scrolling, Shift-horizontal scrolling, or Ctrl cursor-anchored zoom.
_Avoid_: Shift vertical scroll, additive percentage zoom

**Fit-to-window scale**:
The view scale revealing the whole image without enlarging it beyond its native pixel scale.
_Avoid_: Fill-window scale, fit-relative 100%

### Workspace lifecycle

Workspace behavior: [file list](docs/design/workspace-file-list.md), [directory loading](docs/design/large-directory-loading.md), and [document replacement](docs/design/undo-redo-and-file-recovery.md#per-image-history-and-workspace-lifecycle).

**Image directory**:
The directory supplying the images in the current annotation workspace.
_Avoid_: Annotation directory, generic folder

**Standalone file opening**:
Opening one image or annotation document without making its containing directory the image workspace.
_Avoid_: Open image directory, import directory

**Annotation directory**:
The directory supplying and storing the workspace's annotation documents; changing it begins a new workspace editing session.
_Avoid_: Image directory, export directory

**Directory ready state**:
The milestone at which the current image and initial file list are usable, before all derived states are necessarily indexed.
_Avoid_: Directory fully loaded, scan complete

**Workspace index completion**:
The milestone at which all discovered files and their annotation-related states are incorporated into the current session index.
_Avoid_: Directory ready state, first image loaded

**Current annotation document replacement**:
An explicit replacement of the current image's annotation content and storage target that establishes a new history baseline.
_Avoid_: Open file, merge annotations

### Image tools

Processing and recovery behavior: [image tools](docs/design/image-tools.md).

**Image tool target set**:
The explicit current image, selected files, or all workspace images chosen for one image-tool operation, including hidden members.
_Avoid_: Current directory, visible file-list rows

**Canvas display adjustment**:
A non-destructive brightness-and-contrast presentation that changes neither source pixels nor annotations.
_Avoid_: Image adjustment, pixel correction

**Canvas display adjustment scope**:
The current image or whole workspace sharing one Canvas display adjustment.
_Avoid_: Image tool target set, visible file-list rows

**Canvas display adjustment session**:
The lifetime of display-adjustment state within one open annotation workspace.
_Avoid_: Saved image setting, persistent workspace preference

**Workspace display adjustment**:
The master display adjustment shared across the workspace, whose changes clear per-image overrides.
_Avoid_: Batch image processing, persisted display preset

**Current-image display adjustment**:
An absolute per-image override replacing the workspace display adjustment for that image during the session.
_Avoid_: Source-image correction, permanent per-image setting

**Image tool**:
A built-in image transformation prepared through an image processing session.
_Avoid_: Annotation tool, external script

**Automatic image adjustment**:
A repeatable source-pixel-derived suggestion expressed through brightness, contrast, and Gamma values available for manual refinement.
_Avoid_: Automatic contrast, hidden correction layer

**Quick image transform**:
An immediate current-image rotation or flip committed with annotations as one recoverable operation.
_Avoid_: Batch transform, uncommitted preview

**Image quality check**:
An analysis-only inspection that records image-quality findings without modifying files or annotations.
_Avoid_: Automatic repair, image filter

**Image quality finding**:
A derived description of an image-quality problem tied to inspected file content, independent of annotation review state.
_Avoid_: Review state, annotation error

**Image quality result cache**:
Application-owned storage of findings identified by file content and check policy, outside image and annotation directories.
_Avoid_: Annotation document, dataset sidecar

**Specialized image repair**:
An image tool justified by representative problem samples and explicit acceptance criteria.
_Avoid_: Generic filter, unvalidated enhancement

**Geometry-changing image tool**:
An image tool that changes image bounds or dimensions and treats the image and associated annotations as one recoverable unit.
_Avoid_: Pixel-only filter, independent annotation edit

**Image-annotation geometry state**:
The consistent pairing of image dimensions, annotation coordinates, and editable projections in one coordinate space.
_Avoid_: Image size alone, stale annotation snapshot

**Colored frame overlay**:
A red or yellow rectangular outline added over image content, distinct from naturally colored objects or solid regions.
_Avoid_: Every red pixel, every yellow region

**Colored frame repair region**:
The detected frame plus the bounded compression halo eligible for repair.
_Avoid_: Whole image, every near-gray pixel

**Image crop region**:
The rectangle selected to become the current image's new bounds and shared annotation coordinate space.
_Avoid_: Annotation box, file-list selection

**Image crop mode**:
The temporary Canvas state for preparing and adjusting a crop through its own uncommitted history.
_Avoid_: Annotation creation mode, committed crop

**Image processing session**:
The temporary context for preparing an image-tool operation before commit, in its workspace or a tool-specific Canvas mode.
_Avoid_: Annotation session, saved image

**Image processing Undo**:
Reversal of the latest uncommitted operation in the active image processing session.
_Avoid_: Annotation Undo, committed-file recovery

**Committed image processing**:
An image-tool result with a recovery record for every replaced image and associated annotation resource.
_Avoid_: Preview, annotation edit

**Image processing batch commit**:
The all-or-nothing replacement of an entire image tool target set after successful preflight.
_Avoid_: Partial batch, best-effort replacement

**Image processing recovery selection**:
The explicitly selected subset of a committed batch to restore atomically; unselected results remain recoverable.
_Avoid_: Implicit file-list selection, mandatory whole-batch restore

### Annotation history and persistence

Editing, saving, conflicts, and recovery: [history contract](docs/design/undo-redo-and-file-recovery.md).

**Undo**:
A request to reverse the latest reversible change in the applicable editing history.
_Avoid_: Recall, withdraw

**Redo**:
A request to reapply the latest undone change while its history branch remains available.
_Avoid_: Repeat command, restore from recycle bin

**Annotation edit history**:
The reversible annotation changes retained independently for one image within a workspace editing session.
_Avoid_: Application history, workspace history

**Annotation history snapshot**:
An immutable annotation-document state, including annotation order, review state, and session identities, without image pixels.
_Avoid_: Canvas screenshot, copied image

**Annotation edit transaction**:
One complete annotation mutation that either records an atomic change or restores its prior state.
_Avoid_: Direct `set_dirty`, per-event history write

**Pending annotation transaction**:
An unfinished edit or prepared history step owned by one current image, preventing saves of intermediate state.
_Avoid_: Dirty Canvas, background gesture

**History projection**:
Replacement of Canvas and annotation-list content from a history snapshot without creating another edit.
_Avoid_: User edit, recursive history record

**Reversible annotation change**:
A committed change to annotation boxes, stored properties, or current-image review state.
_Avoid_: View change, selection change

**Atomic annotation edit**:
One complete user intention retained as a single reversible annotation change regardless of event or affected-box count.
_Avoid_: Mouse-move event, per-box batch entry

**History result selection**:
The view-state selection derived from boxes affected by Undo or Redo, independent of historical selection.
_Avoid_: Restored historical selection, selection history entry

**Session annotation identity**:
A stable per-box identity within one workspace editing session, reused by history restoration and never written to annotations.
_Avoid_: Persistent annotation ID, geometric matching

**Annotation order**:
The box order shared by the annotation list, drawing layers, and topmost targeting tie-breaks.
_Avoid_: Unordered box set, append-on-restore

**View state**:
Transient presentation and interaction state that neither changes annotation content nor enters annotation history.
_Avoid_: Annotation content, reversible annotation change

**Pending drawing**:
An uncommitted annotation shape whose geometry or label has not yet completed creation.
_Avoid_: Created annotation, reversible annotation change

**Pending box preview**:
The transient rectangle shown from placing the first corner through initial label confirmation, until a new annotation is committed or canceled.
_Avoid_: Selected annotation, selection region, image crop region

**Pending label confirmation**:
The stage of a pending drawing whose box geometry is complete but whose first annotation label has not yet been confirmed.
_Avoid_: Committed annotation, existing-label edit, completed creation

**Automatic overlap hiding**:
Temporary Canvas suppression of boxes containing the pointer in Draw mode before a new rectangle has area, then of other boxes sharing a positive-area intersection with the pending box through initial label confirmation, without changing explicit visibility choices.
_Avoid_: Hide all background boxes, manual visibility toggle, annotation deletion

**Pending annotation gesture**:
A geometry-changing interaction started but not yet committed or canceled.
_Avoid_: Atomic annotation edit, live history entry

**Load-time geometry normalization**:
Clamping stored geometry to image bounds when loading, establishing a clean representation without a user edit.
_Avoid_: Adjust-out-of-bounds history entry, user geometry edit

**Committed annotation creation**:
One atomic edit formed only after valid drawing geometry and label confirmation complete.
_Avoid_: Geometry-only creation, label-only creation

**Workspace editing session**:
The lifetime of one image-directory and annotation-directory pairing, retaining independent per-image histories across navigation.
_Avoid_: Application lifetime, image visit

**Workspace automatic saving**:
The session-scoped annotation-saving mode enabled when a workspace editing session begins.
_Avoid_: Application-lifetime preference, mandatory separate save directory

**Saved annotation baseline**:
The clean in-memory revision paired with its storage target and stored-resource fingerprint, retained independently of history eviction.
_Avoid_: History reset, undo boundary

**Annotation storage resource**:
A physical file or shared metadata object touched by annotation saves and therefore coordinated for writes and conflicts.
_Avoid_: Image-only save lock, independent CreateML record

**Annotation storage target**:
The format and destination selected for one image's document, separate from reversible annotation content.
_Avoid_: Annotation content, Undoable format change

**Active annotation document**:
The explicitly selected stored representation supplying an image's baseline when multiple annotation formats exist.
_Avoid_: First-found document, merged formats

**Empty annotation baseline**:
A successfully stored document state with no boxes or review flag, potentially represented by absence of a file.
_Avoid_: Missing-data error, explicit clear-annotations operation

**Discard unsaved changes**:
Replacement of local annotation content with the verified stored baseline followed by history rebase.
_Avoid_: Undo all, history navigation

**Unsaved image-navigation guard**:
The Save, Discard, or Cancel decision protecting committed unsaved edits before a user-requested image switch.
_Avoid_: Non-blocking dirty indicator, workspace-close summary

**History rebase**:
Replacement of an image's edit history with a new baseline after document replacement or an external mutation.
_Avoid_: Undo, save

**External annotation conflict**:
A stored-resource change conflicting with an unsaved local revision based on its prior content.
_Avoid_: Whole-workspace file watching, automatic merge

**Current annotation live synchronization**:
Synchronization of the current image's stored annotation changes, with only derived index updates for inactive images.
_Avoid_: Whole-workspace document reload, stale file-list status

**History retention limit**:
The bounded per-image and workspace-wide history window available for Undo and Redo.
_Avoid_: Persistent archive, unlimited history

**Annotation history shortcut context**:
The Canvas, annotation list, and non-text workbench focus contexts in which annotation Undo and Redo apply.
_Avoid_: Application-wide shortcut, file-operation undo

**Atomic history execution**:
An Undo or Redo that either applies completely or restores its pre-attempt state without advancing history.
_Avoid_: Partial undo, optimistic cursor advance

**Degraded annotation state**:
A protected dirty state after failed history application and restoration, allowing inspection and rescue while editing and autosave are paused.
_Avoid_: Clean rebase, automatic overwrite

### File recovery

File transaction and restoration rules: [recovery contract](docs/design/undo-redo-and-file-recovery.md#file-operation-recovery-center).

**File operation recovery**:
Explicit session-scoped restoration of completed cross-file operations, separate from annotation Undo and Redo.
_Avoid_: Global Undo, annotation Redo

**File operation recovery entry**:
A one-use record of successfully changed targets retained in the current session's bounded recovery list.
_Avoid_: Persistent audit log, annotation history entry

**Recovered file selection**:
The selection of restored images after deletion recovery, independent of the current image.
_Avoid_: Automatic recovered-image navigation, old row restoration

**File recovery conflict**:
An occupied original path or changed target that prevents exact restoration of a recovery entry.
_Avoid_: Best-effort restore, overwrite confirmation

**Rename recovery**:
The inverse synchronized rename that restores prior paths while preserving content edited under the newer names.
_Avoid_: Old-byte restoration, content rollback

**Review-state recovery**:
A field-level reversal of a cross-file review operation that preserves later annotation-box content.
_Avoid_: Whole-document restoration, box rollback

**Cleared-annotation recovery**:
Exact restoration of cleared documents while their targets still match the operation's empty state.
_Avoid_: Annotation merge, overwrite restore

**Manual trash recovery**:
Restoration through the operating system when trash is available but provides no stable in-application recovery identity.
_Avoid_: Application recovery, permanent-delete fallback

**Trash recovery identity**:
An opaque session handle identifying one successfully recycled path for later availability checks and restoration.
_Avoid_: Original path, filename search

### Annotation interaction

Selection, targeting, and presentation: [annotation interaction](docs/design/annotation-interaction.md).

**Temporary multi-selection mode**:
The transient Ctrl-held Canvas mode for toggling boxes or selecting a fully contained group without moving them.
_Avoid_: Square-drawing mode, generic selection mode

**Selection region**:
The temporary drag rectangle selecting only boxes fully contained within its bounds.
_Avoid_: Intersection region, crop box

**Selection set**:
The same selected boxes projected between Canvas shapes, annotation-instance buttons, and label-group rows.
_Avoid_: Active box, current item

**Bulk selection action**:
A command explicitly targeting the complete annotation selection, such as copying or deletion.
_Avoid_: Batch edit, group transform

**In-image duplication**:
A copy operation creating slightly offset boxes in the current image and selecting the duplicates.
_Avoid_: Clipboard copy, paste

**Clipboard selection**:
A retained snapshot of selected annotation boxes available for pasting independently of its source.
_Avoid_: In-image duplication, all image labels

**Previous-image annotation copy**:
An atomic replacement of current boxes with captured copies from the previous image's active annotation document.
_Avoid_: Live link, source-dependent Redo

**Append paste**:
A paste that preserves existing boxes and selects only the added clipboard copies.
_Avoid_: Replace paste, overwrite labels

### Label colors

Resolution and lifetime: [session label palette](docs/design/session-label-color-palette.md).

**Label color palette**:
The session-only mapping of exact labels to user-chosen display colors, independent of annotation data.
_Avoid_: Application color theme, global label colors

**Label color override**:
One explicit palette entry replacing a label's stable automatic color until removed or the session ends.
_Avoid_: Annotation edit, saved preference

**Label display color**:
The opaque category color shared by matching box outlines, candidate capsules, and annotation-instance controls.
_Avoid_: Per-surface label color, per-box color

### Annotation targeting and feedback

Detailed gestures and visual states: [annotation interaction](docs/design/annotation-interaction.md).

**Corner resize target**:
The corner area that resizes a box along its diagonal while preserving a move target in small boxes.
_Avoid_: Fixed-radius corner target, entire small-box interior

**Box-move target**:
The box interior remaining after corner and edge resize targets are resolved.
_Avoid_: Corner resize target, edge resize target

**Pointer target resolution**:
The deterministic choice of a visible corner, edge, or containing box interior from pointer geometry alone.
_Avoid_: Drawing-order scan, first hit

**Canvas context command surface**:
The transient commands valid for the current blank-area, annotation-selection, or crop context.
_Avoid_: Static Canvas menu, global Edit menu

**Label text hit region**:
The rendered text area eligible only for the unmodified Canvas label-edit double-click.
_Avoid_: Ordinary selection target, hidden label target

**Label text overlap target**:
The label-text region selected for editing when no annotation geometry is targeted at that position.
_Avoid_: Ordinary pointer target, first text hit

**Overlap candidates**:
Visible boxes whose move targets contain the pointer after resize targets are resolved.
_Avoid_: Nearby boxes, hidden candidates

**Overlap target**:
The containing box chosen by strict containment, nearest boundary, then topmost drawing layer.
_Avoid_: Nearest center, drawing-order-only target

**Near-duplicate cluster**:
A pairwise group of similarly sized boxes with closely aligned corresponding image-coordinate boundaries.
_Avoid_: Any overlap, containment pair

**Duplicate-label risk**:
A near-duplicate cluster sharing one label, suggesting accidental repetition without declaring it invalid.
_Avoid_: Confirmed duplicate, save error

**Category-conflict cluster**:
A near-duplicate cluster containing different labels that may represent a category conflict or intentional multi-label interpretation.
_Avoid_: Duplicate-label risk, invalid annotation

**Near-duplicate dismissal**:
A session-only choice suppressing one cluster's feedback until its membership, geometry, or labels change.
_Avoid_: Saved annotation property, permanent validation

**Cluster focus**:
Temporary emphasis of one selected cluster member with peers visually subdued, without changing annotation content.
_Avoid_: Offset geometry, persistent isolation

**Pointer gesture target**:
The box resolved at mouse press and locked until the interaction completes or is canceled.
_Avoid_: Cached hover target, mid-drag retargeting

### Annotation list

Group, instance, filtering, and visibility behavior: [annotation interaction](docs/design/annotation-interaction.md#label-groups-and-instance-strips).

**Label group**:
The current image's boxes sharing exactly the same case-sensitive label.
_Avoid_: Dataset class, case-insensitive class

**Annotation-instance button**:
The numbered in-row control for exactly one annotation box, identified visually by its category-color outline.
_Avoid_: Group button, count badge

**Annotation-instance strip**:
The horizontally scrollable instance controls within a row whose label, total, and aggregate visibility remain fixed.
_Avoid_: Wrapped button grid, clipped instance list

**Label-group rename**:
One atomic label edit of every group member, merging into an existing destination group when needed.
_Avoid_: Row-title-only edit, repeated independent rename

**Annotation-instance label edit**:
One atomic label edit of exactly one box, independent of other boxes sharing its former label.
_Avoid_: Label-group rename, bulk relabel

**Canvas label-edit gesture**:
An unmodified double-click in Selection/Edit that targets one visible box or label and opens its label editor.
_Avoid_: Label-group rename, property editor

**Label-group filter**:
A case-insensitive row filter that changes neither Canvas visibility nor annotation selection.
_Avoid_: Visibility filter, label isolation

**Label-group isolation**:
An explicit command hiding other label groups on the Canvas, independent of list filtering.
_Avoid_: Search, implicit combo-box visibility

**Annotation-list command scope**:
The explicit instance selection or named group targeted by a context command.
_Avoid_: Implicit group selection, ambiguous current item

**Label-group deletion**:
One immediate, atomic, undoable removal of every box in an identified label group.
_Avoid_: Repeated instance deletion, irreversible bulk delete

**Synchronized hover**:
A view-only hover projection between Canvas and annotation list: a box previews itself and its row; a group previews all visible members without becoming a Canvas pointer target.
_Avoid_: Hover selection, current row

**Initial image selection**:
The empty annotation selection established whenever an image becomes current.
_Avoid_: Last-label selection, carried selection

**Visibility toggle**:
The group eye control for showing or hiding boxes without changing selection.
_Avoid_: Selection checkbox, disabled row

### Labels and documents

Candidate membership and storage behavior: [annotation persistence](docs/design/undo-redo-and-file-recovery.md).

**Label**:
The object-class name assigned to an annotation box.
_Avoid_: Tag, category text

**Candidate label**:
A label currently used by committed annotations in the open workspace and offered for reuse, including retained unsaved documents.
_Avoid_: Session label history, predefined class list

**YOLO class index vocabulary**:
The stable mapping between YOLO labels and numeric storage indices, independent of visible candidate membership.
_Avoid_: Candidate labels, sorted class list

**Annotation document**:
The boxes and review state associated with one image, independent of storage format.
_Avoid_: Label file, format file

**CreateML annotation collection**:
A shared stored collection of image records identified by complete image reference; writes and conflicts belong to the complete collection.
_Avoid_: Single-image JSON document, delete-whole-file-by-default

**Annotation workspace**:
The images being annotated, their documents, and the candidate labels derived from them.
_Avoid_: Image folder, save directory

### File list and operations

Search, selection, status, and clipboard behavior: [file list](docs/design/workspace-file-list.md).

**File-list display path**:
An image's path relative to the workspace root, preserving nested directories.
_Avoid_: Absolute-path label, basename-only flattening

**File-list view order**:
The stable workspace image sequence governing rows, visible navigation, and ordered batch commands.
_Avoid_: Base-name-first order, visual-only sort

**File-list filter**:
A conjunctive view by annotation, review, persistence, and quality state, combined with any active search query.
_Avoid_: Image search query, file selection

**Image search command**:
The workbench-wide command focusing the persistent image-search field.
_Avoid_: Context-only file-list shortcut, hidden search popover

**Image search query**:
A session-only literal filename or relative-path condition that combines with file-list filters without changing current image or selection.
_Avoid_: External-directory search, image-content search

**Filtered file navigation**:
The non-wrapping Previous/Next sequence through visible images in file-list view order.
_Avoid_: Full-workspace navigation, wraparound navigation

**File selection set**:
The intentionally selected image files, independent of the current image and retained when filters hide members.
_Avoid_: Current image, opened file

**Current image**:
The single image loaded for viewing and annotation, independent of selected files.
_Avoid_: Selected file, active selection

**File selection context**:
The complete file selection targeted by a file-list context command.
_Avoid_: Right-clicked file only, current image

**File clipboard transfer**:
An explicit transfer of selected images, associated annotation resources, or both to the system clipboard for another application to paste.
_Avoid_: Copy path text, immediate export

**Associated annotation resource set**:
The deduplicated existing annotation files associated with selected images across both workspace annotation locations.
_Avoid_: Active format only, generated selection export

**Image review state**:
The mutually exclusive unreviewed, verified, or questioned classification of an image's annotation document.
_Avoid_: Independent verified and questioned flags, mixed-state toggle

**Review-state representation**:
The active annotation format's stored representation of image review state.
_Avoid_: Pascal-only review file, format conversion

**File annotation state**:
The presence or absence of annotation boxes, independent of review state.
_Avoid_: Combined progress category, review state

**File-list state selection**:
A command replacing file selection with visible matches in one independent annotation or review dimension.
_Avoid_: Combined progress-state selection, cross-dimension implicit filter

**File-list persistence alert**:
The trailing indicator of the most severe active annotation persistence condition, with all conditions available on hover.
_Avoid_: File-name suffix, multiple trailing symbols

**Recoverable image deletion**:
Removal of targeted images with all matching annotation resources through the system trash as logical image-and-annotation targets.
_Avoid_: Permanent deletion, image-only deletion

**Recoverable annotation clearing**:
Removal of targeted annotation resources through the system trash while preserving their images.
_Avoid_: Image deletion, active-format clearing

**Synchronized image rename**:
A basename change preserving directory and extension while updating associated annotation names and image references.
_Avoid_: Rename image only, move image

**Batch rename plan**:
A previewed, conflict-free mapping of selected images to synchronized renames that succeeds as a whole or rolls back.
_Avoid_: Sequential rename prompts, partial batch rename
