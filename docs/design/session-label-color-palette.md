# Session Label Color Palette

## Outcome

Users can assign one opaque display color to an exact, case-sensitive label for the current annotation workspace session. The same resolved color is used for every matching box and label indicator. Settings → Label Color Algorithm selects fixed full-name colors (the default) or maximum color separation for the current workspace session.

This feature is presentation state, not annotation data. Category-to-color mappings never write JSON, another sidecar, or application settings, and never change Pascal VOC, YOLO, or CreateML documents. Only the algorithm choice is remembered in existing application settings. Color changes do not participate in dirty tracking or Undo and Redo.

## Resolution and appearance

Color resolution is:

1. use the session override for the exact label when present;
2. otherwise use the selected automatic algorithm for that exact label.

## Automatic algorithms

Both algorithms are image-independent and return opaque sRGB colors. They do not inspect pixels, change with image brightness, or add background/outline readability treatments.

**Fixed by Full Label Name (default).** SHA-256 of the versioned namespace `labelimg-color-v1\0` plus the full UTF-8 label supplies bounded integer samples for OKLCH hue, lightness (`0.70–0.82`), and chroma (`0.14–0.20`). Out-of-sRGB colors reduce chroma at fixed lightness and hue before 8-bit conversion. No large-integer floating-point RGB extraction is used. Exact names are not trimmed, normalized, or case folded by the color algorithm. The same name has the same RGB independently of dataset, label lookup order, image, and process hash seed. This versioned mapping is locked by regression examples; unrelated feature changes must not silently change it. Fixed colors do not guarantee a minimum distance between arbitrary names.

**Maximum Color Separation (Session).** Build a bounded candidate pool from OKLCH lightness `0.68/0.75/0.82`, chroma `0.12/0.17/0.22`, and hues every five degrees. Reduce chroma into sRGB, quantize, deduplicate RGB values, and measure the resulting colors in OKLab. On a label's first automatic lookup, select the candidate maximizing its minimum squared OKLab distance from all existing resolved session colors. Exact-name SHA-256 breaks equal-distance ties and seeds the first assignment. Candidate-label previews also count as lookups; allocations therefore depend on the dataset's known labels and lookup order, not only committed annotation order. A cached minimum-distance vector allows each additional label to update the pool once rather than comparing against the full assignment history again.

Existing session assignments never move when new labels appear, images change, or annotations are undone, deleted, or restored. Custom overrides take precedence and affect future allocations; editing/restoring an override does not reassign other labels. The candidate pool is finite: distances decrease as the number of categories grows, and colors may repeat once the available candidates are exhausted. This is greedy maximization for each new label, not a global rearrangement of existing colors.

The conversion and distance definitions follow [OKLab/OKLCH](https://www.w3.org/TR/css-color-4/#ok-lab). Gamut reduction retains lightness/hue rather than clipping out-of-range RGB channels directly.

## Appearance

The resolved color is always opaque. It drives box outlines, candidate-label capsules, and annotation-instance outlines. Unselected instance buttons retain the theme background; their selected, hovered, and hidden treatments follow [annotation interaction](annotation-interaction.md). The group label remains plain text. A selected Canvas box derives its translucent fill from the resolved color at the fixed selection opacity; text contrast and hover treatments are derived rather than stored independently.

There are no default drawing colors, per-box colors, independent fill colors, or user-adjustable alpha values.

## Interaction

The annotation panel header opens **Manage Label Colors**. The dialog lists labels currently used on the canvas plus session overrides for labels that are not currently used. Changes are staged until **Save**; **Cancel** leaves the active palette unchanged. Users may choose a color, restore the selected label to automatic color, or restore every override after confirmation.

A label-group context menu provides the direct **Set Label Color** command and, when that label has an override, **Restore Automatic Color**.

Palette changes refresh every matching current-canvas box and label surface immediately without creating an annotation-history transition.

The Settings submenu has two exclusive choices: **Fixed by Full Label Name (Default)** and **Maximum Color Separation**, with concise bilingual purpose descriptions. Switching algorithms refreshes Canvas boxes, candidate-label capsules, and annotation-instance outlines immediately while retaining custom overrides. Returning to the session algorithm within the same workspace reuses its existing assignments. Reset All Settings restores the fixed algorithm.

## Lifetime

Overrides and maximum-separation allocations survive navigation between images in one image-directory workspace. They are cleared when the image directory or annotation directory changes, when a standalone image is replaced or closed, and when the application exits. The selected algorithm survives these transitions and application restarts. Unused overrides remain available in the manager until that workspace session ends; automatic-only allocations do not become custom overrides or manager rows by themselves. No category-color mapping is persisted or synchronized across environments, so session colors may differ in a new workspace or process. Fixed colors recompute identically. Refreshing an unchanged candidate-label list must still resolve colors after a session reset.

## Removed legacy behavior

Default line-color settings and per-box line/fill commands are absent. Annotation readers, domain boxes, history snapshots, writers, clipboard records, and runtime shapes carry no stored fill colors or serialized color placeholders.

## Acceptance checks

Verify the resolution, staging, refresh, and lifetime rules through new and loaded boxes, exact-case label variants, Save/Cancel, algorithm switching, and both override reset actions. Check fixed-color process/order invariance, conversion reference colors, controlled lightness after gamut reduction, and the maximin objective against the final candidate pool. Check remembered algorithm selection and Reset All Settings without persisting allocations or overrides. Palette changes must leave annotation history, dirty state, and annotation files unchanged.
