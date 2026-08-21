# Canvas Tool Rail and Command Surfaces

Design status: approved on 2026-08-07. This document is an implementation contract, not implementation authorization; production UI changes require a separate implementation request and validation.

## Outcome

LabelImg Enhanced uses a single-image annotation workbench with one stable command layout. The left edge is a compact Canvas tool rail rather than a general shortcut catalog. Commands are placed according to what they act on: Canvas tools on the left, current-image workflow at the top, annotation-object commands in the annotation panel and context menu, and view scale in the bottom status bar.

Beginner and advanced layouts are removed. Routine commands never move or disappear because of an interface mode, and the application does not restore a different command layout at the next launch.

## Current-state audit

The current `ToolBar` uses text-under-icon buttons and a class-level mutable minimum size shared by every button. In the audited English runtime, the longest action expanded every button to 411 by 60 logical pixels and the toolbar content size hint to 411 by 1068. At 1180 by 760, the left bar consumed 411 pixels and left approximately 130 pixels for the central Canvas; at 1024 by 720, only the first ten ordinary buttons remained directly visible.

The current beginner list mixes workspace opening, navigation, two review actions, saving, a cycling format command, annotation creation and selection commands, image transforms, and zoom. The advanced list replaces it with a different subset and hides review, selection commands, and zoom. Commands beyond the available height fall behind Qt's small automatic overflow control.

The audit also found mixed raster and SVG icon styles, inconsistent active-state semantics, review actions enabled without an open image, an incomplete format shortcut, and tooltips that omit shortcuts. Offscreen screenshots were suitable for measuring geometry, icon placement, grouping, and overflow but not for judging text rendering or claiming complete accessibility conformance.

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

In Selection/Edit, an unmodified left-button double-click on a visible annotation box or its visible label text replaces the selection with that box and opens the existing single-box label editor. The complete interior, outline, adjustment handles, and label text are valid targets. Create, Pan, and Crop retain their existing double-click behavior, and modifier-assisted double-clicks never open the editor.

Label text participates in the same pointer-target model used by hover, ordinary selection, Ctrl-selection, context menus, and double-click. Its screen-space hit region follows the actually rendered text with a stable two-pixel allowance; hidden boxes and hidden label text have no target. Label candidates precede geometry. Among overlapping label regions, strict containment chooses the innermost smallest region, partial overlap chooses the nearest boundary, and equality within tolerance chooses the topmost annotation layer. The resolved box remains locked for the gesture, and the existing dashed hover outline identifies it without adding a separate label-text highlight.

Double-clicking while several boxes are selected reduces the selection to the resolved box. Every single-box label-edit entry point uses the same pending annotation transaction from dialog opening through cancellation or one atomic commit. Canceling or confirming the existing label creates no history entry; accepting a different label creates one reversible change for that box and its label-derived line color.

The interaction is documented in the bilingual Help shortcut catalog as a Canvas-context mouse gesture. The Selection/Edit tooltip remains unchanged, and the interaction adds neither a special pointer cursor nor label-text hover styling.

Automated validation covers interior, outline, adjustment-handle, inside-label, and outside-label double-clicks; nested, partial, and identical label-region overlap; hidden boxes and labels; inactive Canvas modes and modifier-assisted double-clicks; multi-selection convergence; cancel, no-op, commit, Undo, and Redo; pending-edit save and format guards; and the shared single-box transaction used by Canvas, annotation-instance, F2, Edit-button, and `Ctrl+E` entry points. Label-group double-click remains a group-wide rename and has its own wiring regression.

### Near-duplicate box feedback

Near-duplicate detection is a non-blocking view over the current annotation document. Two similarly sized boxes qualify only when their left and right edges each differ by no more than `max(1 image pixel, 2% of the smaller width)` and their top and bottom edges each differ by no more than `max(1 image pixel, 2% of the smaller height)`. A materially larger box containing a smaller box and ordinary partial overlap never qualify. Membership is evaluated in image coordinates and therefore remains stable across zoom.

Every emitted cluster is pairwise complete and each annotation belongs to at most one cluster. Ambiguous candidate groups are assigned from the pair with the smallest normalized boundary error, with annotation-document order providing the stable tie-break. A cluster sharing one label is a likely-duplicate risk; a cluster containing different labels is a category conflict. Neither state blocks Save, navigation, or export, and neither deletes annotations automatically.

The Canvas paints one fixed-screen-size marker outside each cluster's union bounds. An amber stacked-box icon identifies likely duplicates, while a magenta exclamation icon identifies category conflicts; category conflict dominates when a cluster also contains repeated members of one label. The adjacent number always means total boxes and carries no repeated `×` or `!` prefix. A hover tooltip gives the ordered label distribution and visible count, for example `cat ×2, dog ×1 · 2/3 visible`. A fully hidden cluster has no Canvas marker and remains discoverable from the annotation list.

Markers are static and brighten only slightly on hover. They normally sit just outside the union's top-right corner without a leader line; boundary or collision displacement adds one short leader line, never offsets annotation geometry. Markers remain passive in Draw, Pan, and Crop and are interactive only in Selection/Edit.

Activating a marker opens a non-modal member chooser without changing selection. Members remain in annotation-document order; each compact row shows only ordinal, label, and visibility, while its tooltip carries geometry. Clicking a row or moving with Up/Down immediately selects and focuses that member, collapsing prior multi-selection; Space toggles visibility, F2 opens the shared single-box label editor, Delete performs one undoable single-box deletion, and Esc closes the chooser. The chooser exposes no layer controls. Cluster focus renders peer outlines at about 20% opacity, suppresses peer label text, and retains ordinary selected rendering for the chosen member; closing the chooser, leaving the cluster, switching state, or Undo/Redo clears focus.

The annotation list adds a risk corner to every involved instance button and one unnumbered dominant-risk icon to each affected label group. Category conflict wins the group icon when both risks occur, while the group tooltip still reports separate cluster counts. These signals open the same chooser, including for fully hidden clusters. A cluster may be ignored for the current workspace session; member identity, geometry, or label changes invalidate that dismissal, while selection and visibility changes do not. The annotation-list overflow command restores all ignored findings for the current image. No dismissal state is written into Pascal VOC, YOLO, or CreateML documents.

Both Canvas and annotation-list interactions are documented in the bilingual Help catalog without changing the Selection/Edit tooltip. Validation covers exact and threshold-close boxes, containment exclusion, strict ambiguous grouping, same- and mixed-label clusters, stable total counts, conditional leader lines, mode passivity, label-distribution tooltips, compact rows, immediate click/keyboard focus, dominant group risk, hidden clusters, dismissal invalidation, atomic label/delete Undo and Redo, and large scrollable clusters.

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

Hide All and Show All become one all-annotations-visible state button in the annotation-panel header. The icon and accessible state change with the result, while the View menu retains separate explicit Hide All and Show All commands and their shortcuts.

## Bottom Canvas status

Zoom moves to the bottom-right status area as `minus | slider | plus | percentage menu`. The percentage menu offers Actual Size, Fit to Window, and Fit to Width. Existing zoom shortcuts remain available.

Zoom is view state. It does not change image dimensions, annotation geometry, or the selected annotation storage format.

## Icon and state system

Every Canvas-rail and top quick-action icon uses one 24-by-24 monochrome line-SVG family with shared stroke width, optical bounds, corner language, and visual weight. Legacy raster icons and visually mismatched SVGs are not used on these surfaces. Delete, Review Required, annotation visibility, Rotate, Flip, and other semantically different actions use distinct symbols.

Buttons implement six visible states: default, hover, pressed, selected or checked, disabled, and keyboard focus. Neutral color is the default; the selected Canvas tool uses the theme accent. Disabled never means selected. Focus uses a visible focus indicator that does not depend on color alone.

Every icon-only target provides a localized accessible name and description. Hover and keyboard focus expose a tooltip in the form `Action name (shortcut) — result`, using the same translated action terminology. Split commands identify both the default action and the availability of additional choices.

## Compatibility and behavior preservation

The change reorganizes command surfaces but preserves the underlying file, annotation, image-processing, history, selection, and save behaviors. File and Image menus remain complete catalogs. Existing shortcuts remain unless this document explicitly adds or aliases one.

The persisted beginner or advanced setting no longer changes command placement. Existing installations that contain it migrate to the single stable layout without losing unrelated window, dock, language, or annotation settings.

## Acceptance criteria

- The rail is exactly 52 logical pixels wide, fixed at the left, and contains only Selection/Edit, Draw Box, Pan, a separator, and Crop in the specified order.
- Selection/Edit is active at startup and after Draw Box or Crop commits or cancels. Pan remains active until another tool is chosen; a temporary middle-button pan restores the prior tool.
- Active tools are checkable and visually selected rather than represented by disabling another command.
- No beginner or advanced command list, mode switch, or persisted mode-dependent layout remains.
- At 1024 by 720 and device-pixel ratios 1, 1.5, and 2, every rail tool and every required top command remains reachable without an automatic toolbar overflow arrow.
- Switching between English and Simplified Chinese can expand and contract top labels without changing the rail width or leaving a class-level maximum-size residue.
- Current-image review is one accessible mutually exclusive three-state control and is disabled without an image.
- Annotation format is a direct selector beside Save and never cycles implicitly.
- Rotate and Flip preserve their split-command behavior and responsive collapse order.
- Copy and Delete are absent from the rail and remain capability-synchronized in the annotation panel, context menu, and shortcuts.
- Annotation visibility uses one stateful panel-header button plus explicit View-menu commands.
- Zoom uses the bottom status control and retains existing keyboard shortcuts.
- Every rail and top quick-action icon comes from the unified SVG family and has localized tooltip, accessible name, accessible description, and keyboard focus coverage.
- Text controls retain their native input shortcuts; `V`, `W`, `H`, `C`, `Esc`, navigation, review, and zoom shortcuts activate only in their documented application contexts.
- Source, installed-package, bilingual resource-parity, and high-DPI UI tests pass after implementation.

## Non-goals

This design does not change annotation document formats, box-selection semantics, image-tool processing algorithms, history behavior, file-list selection, or the general content of the File and Image menus. It does not redesign every right-side panel; only the command relocations required by the stable workbench are in scope.
