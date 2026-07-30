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

**Overlap cycle**:
A Ctrl-click sequence at a location shared by multiple visible annotation boxes that selects exactly one candidate at a time, from topmost to bottommost, clearing the rest of the selection set at each step.
_Avoid_: Additive overlap toggle, select-through

**Synchronized selection**:
A selection set whose members are identical on the canvas and in the label list. The label list follows file-explorer conventions: an ordinary click replaces the set, Ctrl-click toggles one member, and Shift-click selects a contiguous range in the currently displayed list order.
_Avoid_: Current row, independent list selection

**Visibility toggle**:
The label-list checkbox that controls whether an annotation box is rendered on the canvas without changing the selection set. Hidden boxes cannot be hit on the canvas but remain selectable in the list and eligible for bulk selection actions.
_Avoid_: Selection checkbox

**Label**:
The object-class name assigned to an annotation box.
_Avoid_: Tag, category text

**Candidate label**:
A previously known label offered for reuse while creating or editing an annotation box.
_Avoid_: Option, list item, tag

**Candidate area**:
The portion of the label-entry dialog that presents candidate labels.
_Avoid_: Candidate frame, label list
