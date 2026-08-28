# Session Label Color Palette

## Outcome

Users can assign one opaque display color to an exact, case-sensitive label for the current annotation workspace session. The same resolved color is used for every matching box and label indicator. Labels without an override keep their stable automatically generated color.

This feature is presentation state, not annotation data. It does not write JSON or another sidecar, does not change Pascal VOC, YOLO, or CreateML documents, does not use application settings, and does not participate in dirty tracking or Undo and Redo.

## Resolution and appearance

Color resolution is:

1. use the session override for the exact label when present;
2. otherwise use the deterministic automatic color derived from the exact label text.

The resolved color is always opaque. It drives box outlines, candidate-label capsules, and annotation-list instance controls. The annotation-list group label keeps its established plain-text style. A selected box derives its translucent fill from the same color at the fixed selection opacity; contrasting text and hover treatments are also derived rather than stored independently.

There are no default drawing colors, per-box colors, independent fill colors, or user-adjustable alpha values.

## Interaction

The annotation panel header opens **Manage Label Colors**. The dialog lists labels currently used on the canvas plus session overrides for labels that are not currently used. Changes are staged until **Save**; **Cancel** leaves the active palette unchanged. Users may choose a color, restore the selected label to automatic color, or restore every override after confirmation.

A label-group context menu provides the direct **Set Label Color** command and, when that label has an override, **Restore Automatic Color**.

Palette changes refresh every matching current-canvas box and label surface immediately without creating an annotation-history transition.

## Lifetime

Overrides survive navigation between images in one image-directory workspace. They are cleared when the image directory or annotation directory changes, when a standalone image is replaced or closed, and when the application exits. Unused overrides remain available in the manager until that workspace session ends.

## Removed legacy behavior

The old default line-color setting and unreachable per-box line/fill color commands are deleted. Annotation reader tuples, domain boxes, history snapshots, writer inputs, clipboard records, and runtime shapes no longer carry stored fill colors or serialized color placeholders.

## Acceptance checks

- Setting a label color updates all current boxes with that exact label and the corresponding label surfaces.
- Labels that differ only by case remain independent.
- New and loaded boxes resolve their color from the active palette.
- Restoring one label or all labels returns to deterministic automatic colors.
- Palette changes do not make the document dirty and Undo or Redo does not change palette entries.
- Navigation within one directory retains overrides; changing or closing the workspace clears them.
- Saving annotations or application settings writes no palette data.
