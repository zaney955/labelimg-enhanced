# LabelImg Enhanced Context

This context defines the project identity and the language used for selecting and operating on annotation boxes in LabelImg.

## Language

**LabelImg Enhanced**:
The independently maintained derivative whose GitHub repository and Python distribution are named `labelimg-enhanced`, whose import package is `labelimg`, and whose application name and command remain `LabelImg` and `labelImg`. Its first independent release is version `1.9.0`, continuing from the upstream `v1.8.6` baseline.
_Avoid_: Upstream LabelImg, GitHub fork, `libs` distribution

**Temporary multi-selection mode**:
A transient canvas state entered while Ctrl is held, shown with a crosshair cursor, in which a click toggles one annotation box and a drag creates a selection region without moving an annotation box. Releasing Ctrl ends the mode but preserves the selection set.
_Avoid_: Square-drawing mode, generic selection mode

**Selection region**:
A dashed, lightly translucent rectangle drawn during temporary multi-selection mode that selects only annotation boxes fully contained within its bounds.
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
A snapshot of every annotation box in the selection set, retained for pasting into another image.
_Avoid_: In-image duplication, all image labels

**Append paste**:
A paste operation that adds the clipboard selection to the target image without removing its existing annotation boxes. The newly pasted boxes replace the prior selection set.
_Avoid_: Replace paste, overwrite labels

**Selected appearance**:
The visual state of a selected annotation box: an opaque outline in its own label color and a translucent fill in the same color at 100/255 opacity. Hover feedback does not fill an unselected box, so it remains distinct from selection.
_Avoid_: Default blue fill, white selection outline

**Selected label text appearance**:
The visual state of label text belonging to every selected annotation box: white text on a black background at about 60% opacity, with a small rounded rectangle and about two pixels of padding around the text. It remains at the annotation box's existing top-left position. Hovering without selection does not apply this appearance, and hidden label text remains hidden.
_Avoid_: Label-list highlight, active-box-only label, hover label highlight

**Corner resize target**:
The interactive area at an annotation-box corner that resizes the box along the corner's geometric diagonal. It contracts for very small boxes so that a distinct box-move target remains available.
_Avoid_: Fixed-radius corner target, entire small-box interior

**Box-move target**:
The annotation-box interior that remains after corner and edge resize targets are resolved and moves the whole box when dragged.
_Avoid_: Corner resize target, edge resize target

**Label text placement**:
The label text position separated from the annotation-box outline, normally above its top-left corner and moved inside the box when the canvas boundary leaves insufficient space above.
_Avoid_: Text baseline on the outline, clipped label text

**Overlap cycle**:
A Ctrl-click sequence at a location shared by multiple visible annotation boxes that selects exactly one candidate at a time, from topmost to bottommost, clearing the rest of the selection set at each step.
_Avoid_: Additive overlap toggle, select-through

**Synchronized selection**:
A selection set whose members are identical on the canvas and in the label list. The label list follows file-explorer conventions: an ordinary click replaces the set, Ctrl-click toggles one member, and Shift-click selects a contiguous range in the currently displayed list order.
_Avoid_: Current row, independent list selection

**Selected label-list appearance**:
The equal-emphasis visual state of every selection-set member in the label list: its label background is preserved, its text is bold, and a slim inset theme-accent marker appears at the left without surrounding the row.
_Avoid_: Full blue border, primary row, active-row emphasis

**Initial image selection**:
The empty selection set established whenever an image becomes current, regardless of whether it was opened directly, reached by navigation, chosen from the file list, or revealed after deletion.
_Avoid_: Last-label selection, carried selection

**Visibility toggle**:
The right-aligned label-list eye control that changes whether an annotation box is rendered on the canvas without changing the selection set. An open eye means visible; a subdued eye-off means hidden. Hidden boxes cannot be hit on the canvas but remain selectable in the list and eligible for bulk selection actions.
_Avoid_: Selection checkbox, disabled row

**Label**:
The object-class name assigned to an annotation box.
_Avoid_: Tag, category text

**Candidate label**:
A previously known label offered for reuse while creating or editing an annotation box.
_Avoid_: Option, list item, tag

**Candidate area**:
The portion of the label-entry dialog that presents candidate labels.
_Avoid_: Candidate frame, label list

**Annotation document**:
The annotation boxes and review status associated with one image, whether stored as Pascal VOC, YOLO, or CreateML.
_Avoid_: Label file, format file

**CreateML annotation collection**:
A physical CreateML JSON file that may contain annotation-document records for multiple images. File operations target the uniquely matching image record and remove the physical collection only when no records remain; before destructive record removal rewrites a retained collection, its complete prior version is preserved in the system recycle bin.
_Avoid_: Single-image JSON document, delete-whole-file-by-default

**Annotation workspace**:
The images being annotated together with their corresponding annotation documents and the candidate labels discovered from them.
_Avoid_: Image folder, save directory, dataset

**File-list display path**:
The image path shown in the file list relative to the opened annotation-workspace root. The root itself is omitted while nested folders remain visible; the full absolute path remains the image identity and is available on hover.
_Avoid_: Absolute-path label, basename-only flattening

**File selection set**:
The zero or more image files intentionally selected in the file list, independently of the current image. An ordinary click replaces the set immediately, Ctrl-click toggles one member, Shift-click selects a contiguous range, Ctrl+A selects every file while the file list has focus, and clicking empty list space clears the set. During the system double-click interval, the prior set may retain only its blue appearance so the first half of a double-click never flashes it as unselected; file commands and the selection count already target the newly clicked file.
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

**File annotation state**:
The one mutually exclusive progress category shown for an image in the file list: unannotated when it has neither annotation boxes nor a review state; annotated when it has boxes but no review state; verified when its review state is verified; or questioned when its review state is questioned. File selection by state uses these same visible categories.
_Avoid_: File-system status, overlapping status filter

**Recoverable image deletion**:
Removal of one current image or every image in a file selection context by moving each image and all matching Pascal VOC, YOLO, and CreateML annotation documents from both workspace annotation locations to the system recycle bin. Deletion does not preserve or separately prompt for unsaved changes to a targeted current image.
_Avoid_: Permanent deletion, image-only deletion, active-format-only cleanup

**Recoverable annotation clearing**:
Removal of all Pascal VOC, YOLO, and CreateML annotation documents associated with every image in a file selection context by moving the documents to the system recycle bin while preserving the images. Clearing a targeted current image also discards its unsaved annotation changes and leaves it open as unannotated.
_Avoid_: Image deletion, active-format clearing, hiding annotations

**Synchronized image rename**:
A rename that preserves an image's directory and extension while changing its base name together with all matching annotation-document names and embedded image references. The renamed identity remains the current image or a member of the file selection set when it held that role before the rename.
_Avoid_: Rename image only, move image, convert image

**Batch rename plan**:
A previewed, conflict-free mapping from a file selection context to synchronized image renames. Names are generated in the pre-rename file-list order from a shared prefix, a template containing original-name or sequence tokens, a shared suffix, and the unchanged extension; the plan succeeds as a whole or is rolled back.
_Avoid_: Sequential rename prompts, partial batch rename, automatic conflict suffix
