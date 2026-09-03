# Session Label Color Palette

## Outcome

Users can assign one opaque display color to an exact, case-sensitive label for the current annotation workspace session. The same resolved color is used for every matching box and label indicator. Labels without an override keep their stable automatically generated color.

This feature is presentation state, not annotation data. It does not write JSON or another sidecar, does not change Pascal VOC, YOLO, or CreateML documents, does not use application settings, and does not participate in dirty tracking or Undo and Redo.

## Resolution and appearance

Color resolution is:

1. use the session override for the exact label when present;
2. otherwise use the deterministic automatic color derived from the exact label text.

The resolved color is always opaque. It drives box outlines, candidate-label capsules, and annotation-instance outlines. Unselected instance buttons retain the theme background; their selected, hovered, and hidden treatments follow [annotation interaction](annotation-interaction.md). The group label remains plain text. A selected Canvas box derives its translucent fill from the resolved color at the fixed selection opacity; text contrast and hover treatments are derived rather than stored independently.

There are no default drawing colors, per-box colors, independent fill colors, or user-adjustable alpha values.

## Interaction

The annotation panel header opens **Manage Label Colors**. The dialog lists labels currently used on the canvas plus session overrides for labels that are not currently used. Changes are staged until **Save**; **Cancel** leaves the active palette unchanged. Users may choose a color, restore the selected label to automatic color, or restore every override after confirmation.

A label-group context menu provides the direct **Set Label Color** command and, when that label has an override, **Restore Automatic Color**.

Palette changes refresh every matching current-canvas box and label surface immediately without creating an annotation-history transition.

## Lifetime

Overrides survive navigation between images in one image-directory workspace. They are cleared when the image directory or annotation directory changes, when a standalone image is replaced or closed, and when the application exits. Unused overrides remain available in the manager until that workspace session ends.

## Removed legacy behavior

Default line-color settings and per-box line/fill commands are absent. Annotation readers, domain boxes, history snapshots, writers, clipboard records, and runtime shapes carry no stored fill colors or serialized color placeholders.

## Acceptance checks

Verify the resolution, staging, refresh, and lifetime rules through new and loaded boxes, exact-case label variants, Save/Cancel, and both reset actions. Palette changes must leave annotation history, dirty state, annotation files, and application settings unchanged.
