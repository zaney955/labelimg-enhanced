# Canvas Tool Rail and Command Surfaces

Current command-surface contract. [ADR 0016](../adr/0016-keep-the-left-rail-dedicated-to-canvas-tools.md) records the fixed-rail decision; [menu information architecture](menu-information-architecture.md) owns the complete menu catalog.

## Outcome

LabelImg Enhanced uses a single-image annotation workbench with one stable command layout. The left edge is a compact Canvas tool rail rather than a general shortcut catalog. Commands are placed according to what they act on: Canvas tools on the left, current-image workflow at the top, annotation-object commands in the annotation panel and context menu, and view scale in the dedicated status strip below the Canvas.

Beginner and advanced layouts are removed. Routine commands never move or disappear because of an interface mode, and the application does not restore a different command layout at the next launch.

## Current-state audit

The former text-under-icon toolbar mixed unrelated commands, changed with beginner/advanced mode, and could consume 411 logical pixels of width while overflowing vertically at ordinary window sizes. The fixed rail and contextual controls below replace that layout; the audit describes the retired UI, not the current runtime.

## Left Canvas tool rail

The rail is fixed to the left edge and is not movable, floatable, closable, or rotatable. It is 52 logical pixels wide and uses 44-by-44 icon-only targets with 24-by-24 icons.

Its complete top-to-bottom order is:

1. Selection/Edit — default tool, `V`.
2. Draw Box — one-shot tool, `W`.
3. Pan — persistent tool, `H`.
4. Separator.
5. Crop — checked while its Canvas session is active, `C`.

Selection and Edit are one tool. It selects annotation boxes and directly edits their geometry and properties without a separate Edit mode. Draw Box returns to Selection/Edit after one valid box is committed or creation is canceled. Leaving Crop after apply or cancel also returns to Selection/Edit. `Esc` cancels the active Canvas operation and returns to Selection/Edit; legacy `Ctrl+J` remains a temporary compatibility alias for entering the default tool.

Pan allows left-button dragging from any image position without selecting or moving annotation boxes. Middle-button dragging temporarily pans from any other Canvas tool and then restores that tool. `Space` remains the current-image Verified shortcut and is not reassigned to temporary pan.

### Direct single-box label editing

An unmodified double-click on a visible box or its visible label in Selection/Edit opens the shared single-box label editor. [Annotation interaction](annotation-interaction.md) owns target resolution, transaction behavior, and all equivalent entry points; the bilingual Help catalog documents the gesture without changing the tool tooltip.

### Near-duplicate box feedback

Passive Canvas and annotation-list signals identify closely aligned boxes and open a non-modal member chooser. [Annotation interaction](annotation-interaction.md) owns detection thresholds, grouping, marker/list appearance, chooser commands, and session dismissal. The signals are interactive only in Selection/Edit and never block Save, navigation, or export.

Copy, Delete, Hide All, Show All, workspace entry, navigation, review state, Save, annotation format, Rotate, Flip, and zoom do not appear in the rail. The rail never uses automatic overflow; all four tools remain visible at every supported window height.

## Top command surface

The top command surface has four task groups in reading order:

1. Workspace entry: Open Image Directory as the primary split command, with Open File in its menu.
2. Current-image context: Previous, image position and count, Next, followed by the three-segment `Unreviewed | Review Required | Verified` control.
3. Image quick actions: separate Rotate and Flip split commands. Their default clicks remain Rotate Clockwise 90 Degrees and Flip Horizontally; their menus expose the approved alternatives.
4. Saving context: explicit annotation-format selector, automatic-save state, and Save.

The review control always shows exactly one current-image state and remains visible even when the annotation panel is hidden. It replaces the two unselected Verify and Review Required toolbar buttons. Its segments are disabled when no image is open.

The annotation-format selector sits beside Save, displays the current format, and directly lists Pascal VOC, YOLO, and CreateML. It replaces the command that cycles formats on each click and continues to use the existing pending-edit and storage-transition safeguards.

## Responsive priority

The top surface reflows by explicit priority without increasing the application's minimum width, adding horizontal scrolling, or exposing Qt's automatic toolbar overflow arrow.

When horizontal space becomes insufficient:

1. Rotate and Flip collapse into one labeled Image Quick Actions menu.
2. Open Image Directory becomes an icon-only split button without changing its primary or secondary action.
3. Navigation, image position and count, review state, annotation format, and Save remain directly visible.

The 1024-by-720 layout is a required supported baseline. The same logical hierarchy must remain usable at device-pixel ratios 1, 1.5, and 2 and in both Simplified Chinese and English.

## Annotation commands and visibility

Copy and Delete remain available through explicit buttons in the annotation panel, the Canvas context menu, and `Ctrl+D` and `Delete`. They are enabled from selection capabilities and never styled as active Canvas tools.

### Canvas context command surface

[Annotation interaction](annotation-interaction.md) owns the transient, target-scoped Canvas menu, keyboard invocation, and native menu behavior. Crop exposes its own adjustment/apply/cancel commands, Draw uses secondary click to cancel, and Pan has no context menu.

Hide All and Show All become one all-annotations-visible state button in the annotation-panel header. The icon and accessible state change with the result, while the View menu retains separate explicit Hide All and Show All commands and their shortcuts.

## Bottom Canvas status

Coordinate and zoom placement revision approved and implemented on 2026-09-03.

A dedicated status strip sits immediately below the Canvas, aligned with its width rather than extending beneath the annotation and file panels. Image pointer coordinates and annotation size appear on the left, with zoom on the right as `minus | slider | plus | percentage menu`. The percentage menu offers Actual Size, Fit to Window, and Fit to Width. Existing zoom shortcuts, range behavior, and cursor anchoring remain unchanged. Application-wide status messages and directory-loading controls remain separate from this strip.

X/Y are zero-based original-image pixel indices, independent of zoom and pan. Only points inside the rendered image have valid indices, from zero through width minus one and height minus one; outside the image or after leaving the Canvas, the fields display unavailable placeholders rather than stale, negative, or out-of-range values. Refreshes after view changes apply the same validity rule.

W/H remain separate from X/Y and describe the actual annotation rectangle, including the current drawing preview after image-boundary and square constraints. While drawing or adjusting a box, moving outside the image does not hide W/H or substitute raw pointer displacement: unchanged geometry retains the same size, and genuine changes in the constrained rectangle update it. This readout change does not freeze annotation interaction or alter its existing boundary rules.

When no rectangle is being drawn, adjusted, or hovered, W/H have no visible text, including no labels or unavailable placeholders. The empty readout retains its reserved space so showing or clearing dimensions never moves the zoom slider.

Responsive layout uses the Canvas's available width, including changes caused by resizing side panels. The slider shortens first; if a single row still cannot fit, readouts and zoom occupy two rows without hiding controls or truncating values; the X/Y and W/H groups can also stack within the readout area when necessary. Readout changes and percentage digit changes must not move the slider while it is dragged. The strip does not overlay the image or conflict with the existing display-adjustment overlay.

Zoom is view state. It does not change image dimensions, annotation geometry, or the selected annotation storage format.

### Zoom scale and navigation

`100%` means one image pixel per logical screen pixel. Fit to Window shows the complete image without enlarging a small image beyond `100%`; fit commands report their actual native-pixel-relative scale. The logarithmic slider has nominal bounds of `1%`–`600%`, with safe per-image bounds expanded for exact Fit to Window, Fit to Width, and retained manual scales. That active range applies to every manual zoom input. Zoom remains inactive without an image.

All standard incremental zoom commands multiply or divide by `1.10` and snap to `100%` for one step when crossing it. High-precision wheel deltas retain proportional continuous scaling. Ordinary wheel scrolls vertically, Shift+wheel scrolls horizontally, and any gesture containing Ctrl zooms; Ctrl takes precedence over other modifiers.

Cursor-anchored zoom keeps the same image point at the same viewport position, using the nearest image-boundary point when the pointer lies outside the image. Exact anchoring takes priority over automatic centering even when the scaled image fits inside the viewport. Image search uses `Ctrl+F`; Fit to Window uses `Ctrl+0`.

### Crosshair magnifier control

A checkable magnifier button sits immediately before zoom in the bottom Canvas strip, with a 28-by-28 target and localized name, checked state, and `M` tooltip. It shares its action with View, is unavailable without an image, remembers the user's preference, and only presents the loupe during drawing. This is a view aid rather than a mutually exclusive tool, so it is kept out of the left rail. Its width participates in the strip's existing responsive stacking; readout changes still do not move controls. [Annotation interaction](annotation-interaction.md) owns the loupe's content and edge positioning.

## Icon and state system

Canvas-rail and top quick-action icons follow the shared [24-by-24 duotone operation icon system](../icon-design-system.md), including its stroke, optical bounds, semantic motifs, and palette. Legacy raster icons and mismatched SVG styles are excluded.

Buttons implement six visible states: default, hover, pressed, selected or checked, disabled, and keyboard focus. Button surfaces are neutral by default; the selected Canvas tool uses the theme accent. Disabled never means selected. Focus uses a visible focus indicator that does not depend on color alone.

Every icon-only target provides a localized accessible name and description. Hover and keyboard focus expose a tooltip in the form `Action name (shortcut) — result`, using the same translated action terminology. Split commands identify both the default action and the availability of additional choices.

## Compatibility and behavior preservation

The change reorganizes command surfaces but preserves the underlying file, annotation, image-processing, history, selection, and save behaviors. File and Image menus remain complete catalogs. Existing shortcuts remain unless this document explicitly adds or aliases one.

The persisted beginner or advanced setting no longer changes command placement. Existing installations that contain it migrate to the single stable layout without losing unrelated window, dock, language, or annotation settings.

## Acceptance criteria

Validate the surface and state contracts above at 1024 by 720, device-pixel ratios 1, 1.5, and 2, and in both languages, including label expansion and contraction without stale shared button sizes. Text inputs retain their native shortcuts; Canvas, navigation, review, and zoom shortcuts activate only in their documented contexts. Source and installed-package validation must both cover icons, accessibility, localization, and layout.

## Non-goals

This document owns command placement, Canvas readouts, and view navigation. [Annotation interaction](annotation-interaction.md), [image tools](image-tools.md), [history and recovery](undo-redo-and-file-recovery.md), and [file-list interaction](workspace-file-list.md) own their respective behavioral contracts.
