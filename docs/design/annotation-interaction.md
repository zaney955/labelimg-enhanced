# Annotation Interaction

This is the current contract for selecting, targeting, and presenting annotation boxes and label groups. Terminology is in [CONTEXT.md](../../CONTEXT.md); [Canvas command surfaces](canvas-tool-rail.md) own tool placement and zoom, [annotation history](undo-redo-and-file-recovery.md) owns transactions and persistence, and the [session palette](session-label-color-palette.md) owns label colors.

## Pending box preview

Draw mode uses one reverse-screen crosshair across the entire visible Canvas, including margins outside the image. It follows the pointer before drawing and the constrained moving corner while drawing. Its horizontal and vertical arms share one mask; the center and crossings with the pending box invert once. The native small drawing cursor is hidden only within the Canvas, preserving ordinary pointers in category dialogs and other controls. Ctrl multi-selection temporarily uses its ordinary selection cursor; releasing Ctrl restores the Canvas crosshair. Leaving the Canvas or Draw mode clears it.

From placing the first corner through initial category confirmation, the preview emphasizes precise alignment and minimal obstruction of the target. Its appearance distinguishes unfinished creation from committed category-colored annotations.

The solid outline defaults to 1.5 logical screen pixels wide and follows the configured annotation line width and follows the Windows reverse-screen cursor rule: fully covered displayed RGB channels become `255 - channel`. Gray backgrounds yield inverted gray, colored backgrounds yield complementary colors, and pure black and white interchange. Near-middle gray intentionally has little contrast with its inverse. This follows the reverse-screen mask behavior in [Microsoft's cursor documentation](https://learn.microsoft.com/en-us/windows/win32/menurc/using-cursors) and the raster operations described by [DrawIconEx](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-drawiconex).

The interior receives a subtle white overlay at approximately 6% opacity (`15/255`), without patterned fill or a connecting diagonal. This temporary Canvas presentation slightly brightens the enclosed image without modifying source pixels. It remains through initial category confirmation and disappears when creation is confirmed or canceled. The lift excludes the reverse-screen geometry, preserving the outline, guides, and marker's existing inversion. While geometry is being drawn, the first corner has one solid circular marker approximately four logical screen pixels in diameter. The moving corner is indicated by the crosshair. Canvas-wide horizontal and vertical alignment guides use crisp, device-aligned lines using the configured annotation line width and meet at the actual constrained corner, including image-boundary and square constraints. Marker and guides use the same reverse-screen treatment. These screen dimensions remain stable across image zoom and display density.

Reversal acts on the already displayed Canvas pixels, including display adjustments and any visible annotations underneath. Geometry is combined into one mask before applying white Difference composition, so overlapping outlines, guides, and markers reverse each pixel only once. Antialiasing affects boundary coverage only. There are no brightness thresholds, averaged sampling strips, or palette approximations; fixed portions remain stable when the endpoint moves or a partial repaint occurs. Image bounds clip the outline, interior lift, and starting marker; Canvas and repaint bounds clip the crosshair arms. View changes reproject a stationary pointer before repainting.

Width and height remain in the Canvas status strip and report the constrained preview geometry. Preview drawing uses that same floating-point geometry. It operates on rendered pixels even when the displayed pixmap resolution differs from the annotation coordinate space.

### Pending label confirmation

Completing geometry leaves a static reverse-screen outline and the subtle interior lift while the initial category chooser is open. Alignment guides and the start marker disappear. The new box remains visually pending throughout modal repaints and is excluded from ordinary category-colored shape drawing, so there is no intermediate green outline.

Confirming the category ends the preview and resolves the committed box's category color. Canceling removes the new box and its preview. Default-label creation follows the same boundary without displaying the chooser. Scene replacement and drawing cancellation clear temporary presentation state; they do not leave a ghost outline.

### Category chooser

The compact native dialog presents a category heading and result count, one name/search field, the candidate grid, then Cancel and the primary confirmation button. It has no title-bar context-help button. Text and empty-result feedback follow the application language; category names remain unchanged.

Candidates use naturally sorted numeric name chunks, matching the annotation panel (`LM2`, `LM3`, `LM10`). Live case-insensitive filtering ranks exact matches, prefix matches, then contained matches, retaining natural order within each tier. Filtering only projects the [workspace candidate vocabulary](undo-redo-and-file-recovery.md#candidate-labels); it never creates a category. Unmatched nonempty text can still be confirmed as a new annotation name. Empty text cannot confirm.

Each candidate has an eight-pixel opaque category-color strip at its left, a solid same-color outline (1.4 pixels normally, 1.8 on hover, 2.2 when selected), small four-pixel corner radii, and centered theme-colored name text. Its pale category-color fill uses the same `48/255` alpha constant as selected annotation-list instance buttons. Full names remain in tooltips when screen limits require elision.

All cells share one width measured from the longest name in the complete current candidate pool plus the strip, compact padding, and border allowance. The grid uses up to four columns, reducing columns before shortening names on narrow screens. Dialog dimensions are capped at 80% of the available screen width and 90% of its height; large pools scroll vertically. Filtering retains the full pool's geometry so targets and the window do not jump while typing. A candidate refresh may resize for a changed vocabulary but preserves an active draft and filter.

Opening the chooser shows all candidates even when the previous name is prefilled and selected for replacement. Clicking a candidate fills the name without narrowing the current results; double-click confirms. Up/Down from the name field selects results and updates the draft while retaining typing focus. Enter confirms the current draft; Escape cancels through the existing pending-annotation boundary. Reopening clears the old filter. Color refreshes retain the full vocabulary rather than replacing it with the filtered subset.

The Canvas tracks the pending label shape only as presentation state. Geometry finalization, scene membership, label assignment, annotation transactions, Undo/Redo, and persistence retain their existing ownership and commit sequence.

## Crosshair magnifier

The checkable magnifier button lives in the Canvas status strip immediately before the zoom controls; View exposes the same action. `M` toggles it while the Canvas or its button has focus, including mid-draw, without consuming typing in label or search fields. Its enabled preference persists, initially off. When enabled, it appears before placing the first corner and during geometry drawing; Ctrl selection, panning, leaving idle drawing, and initial label confirmation suppress the loupe.

The loupe follows the actual constrained crosshair center and defaults to the lower right with a 20-logical-pixel gap. Placement protects the entire normalized pending rectangle, including its outline and a visual clearance, in widget coordinates. It searches the free strips on all four sides of that rectangle within the visible Canvas, preferring a full 160-by-176-logical-pixel loupe near the default position. When no full-size placement fits, it uses the largest safe compact placement (at least 64 by 80); when no safe placement exists, it temporarily disappears and returns once space is available. Before the first corner and for zero-area boxes, the cursor is still protected. Every final position must remain fully inside the viewport with a six-pixel margin and outside the protected region; edge correction never pushes the loupe back across the pending box. These rules apply to every drawing direction, image constraint, view offset, and zoom. It samples the displayed image (including display adjustments) without annotation overlays, uses nearest-neighbor detail at at least 4× image resolution and twice the current view scale, and contains a reverse-screen center crosshair plus a two-row footer: rounded magnification followed by the localized hint “M 开关放大镜” / “M: Toggle magnifier”. The hint wraps in compact layouts and reserves its measured height; a loupe too short to retain readable text and image detail stays hidden. Out-of-image detail stays blank rather than stretching edge pixels. It is paint-only and does not intercept pointer input.

## Annotation display settings

View → Annotation Display Settings opens a live preview dialog. Box line width ranges from 0.5 to 6 logical screen pixels (default 1.5); label text size ranges from 6 to 128 screen points (default 25). Both remain constant on screen while zooming and persist across launches. The same line width applies to committed boxes, pending rectangles, the full-Canvas crosshair before and during drawing, and the magnifier crosshair. All widths use logical screen pixels and remain stable across zoom; the shared reverse-screen mask still inverts crossings only once. Cancel restores both original values; Restore Defaults previews the defaults. Label painting, hit regions, protection regions, and drawing cache invalidation use the current size.

## Automatic overlap hiding

View provides two independent, persisted checkable options, both initially off:

- **Hide Boxes and Labels Covering the Crosshair Center / 隐藏覆盖准星中点的框和文字** controls suppression before and during drawing, plus local clipping inside the pending rectangle during drawing and initial label confirmation.
- **Hide Parts Obscuring Selected Annotations / 隐藏遮挡选中标注的部分** controls local clipping around selected, moved, or resized targets.

Neither option has a keyboard shortcut. Existing installations migrate the former combined preference to both new options unless that option already has its own saved value. Reset All Settings restores both to off.

Outside an active drawing crosshair, each visible selected annotation protects its box and visible label, including a selected label's background padding. These areas jointly mask only the covered portions of other annotations' outlines, fills, vertices, and text; every uncovered portion remains visible. All visible members of a selected group are protected together. Hovering a Canvas annotation or annotation-list instance/group retains its highlight but does not add protection or hide other annotations. Protected annotations are drawn complete above the clipped background in their original order, with a dragged annotation last. They do not clip one another. Manually hidden targets contribute no mask and stay hidden. Labels that are not displayed contribute no mask; label visibility follows the same rule as painting, including the label forced visible by near-duplicate focus.

Before the first corner and throughout geometry drawing, the crosshair center independently controls box and label presentation. Every explicitly visible existing box whose normalized geometric bounds contain the center has its entire outline, fill, and vertices temporarily suppressed. Every displayed label whose text/background bounds contain the center is independently hidden in full. Hiding a box does not hide an unrelated label outside the center, and hiding a label does not hide its box unless the center also lies in that box. Multiple containing boxes or labels are all suppressed. Boundary contact counts; labels use the same displayed geometry as painting, including selected background padding. Whole-component suppression ends as soon as the center leaves the original bounds; the pending rectangle can still clip covered portions. The source image and the unified crosshair remain visible. This drawing intent takes priority over selection protection. Edit-mode hover remains highlight-only.

Whole-component suppression uses the constrained crosshair center, including reverse drawing, image-boundary constraints, and square constraints; the long crosshair arms do not suppress other annotations. During geometry drawing, the normalized pending rectangle also clips covered portions of other annotations' outlines, fills, vertices, and text, even when the center is outside those annotations. Uncovered portions remain visible, and leaving an annotation's bounds restores its components outside the pending rectangle. Point containment and pending geometry are evaluated in image coordinates, so zoom, display density, and viewport changes do not introduce a fixed clearance radius or width. Opening the initial category chooser ends center-based suppression and retains the pending rectangle's local clipping until creation completes or is canceled. Ctrl multi-selection and panning suspend idle center-based suppression. Leaving the Canvas before starting a box restores affected components; scene replacement clears the tracked pointer. Existing visible selections can protect annotations in Draw mode when no drawing crosshair or pending drawing is present; protected shapes are painted separately above the cached background.

Targets update immediately on selection, visibility, geometry, zoom, and label-display changes. Selection protection persists after pointer departure or drag release until deselection. Clearing selection restores other annotations even if the pointer remains over a previously selected target. Finishing or canceling creation/dragging returns to protection derived from the current selection or active drawing crosshair. Mode and scene changes discard their transient targets; turning the option off restores explicitly visible background portions immediately.

Automatic overlap hiding is a Canvas presentation filter, independent of explicit visibility. It does not change annotations, history, list eye states, or the user's manual visibility choices. Target resolution continues to use original explicitly visible geometry, so temporary clipping cannot make a target unreachable or cause hover flicker.

Near-duplicate Canvas markers disappear only when every explicitly visible member's box and displayed label are suppressed, considering both center-based component hiding and local clipping. Protected or partially clipped members retain their marker. The mask and protected set are computed once for each marker layout. Cluster membership, total counts, and annotation-list risk feedback stay unchanged.

Draw mode retains a transparent annotation layer for the visible viewport. Box and label visibility are cached separately; changes damage the affected annotation bounds and intersecting peers while unrelated annotations retain their cached pixels. Local clipping for the pending rectangle during drawing and initial label confirmation, or for selected targets, is applied during composition. Protected targets are excluded from the background cache and painted complete afterward. The layer tracks geometry, appearance, selection, explicit visibility, and component presentation; zoom, display density, viewport changes, scene replacement, and annotation order changes rebuild it. Source-image display adjustments remain beneath the transparent layer and the reverse-screen preview remains above it. Leaving Draw mode releases the layer. Its allocation is capped at 64 MiB; oversized captures fall back to ordinary painting with the same box/label visibility and clipping. Pixel comparisons cover cached/direct rendering, separate box and label containment, nested boxes, constrained endpoints, selected targets, and restoration when protection ends.

## Selection and pointer targets

Every newly opened or navigated image starts with an empty annotation selection. Canvas and annotation-list selection stay synchronized; file selection is independent.

- Holding Ctrl enters temporary multi-selection with a crosshair. A click toggles one box; a dragged selection region replaces the selection with fully contained boxes. The region is dashed and lightly translucent. After its drag threshold, single-box hover is suppressed until release recomputes the pointer target.
- Ctrl suppresses resize cursors and enlarged corners while retaining complete-box hover. Releasing it restores ordinary editing without clearing selection.
- Ordinary geometry edits require one selected box. Copy, duplicate, delete, and explicitly scoped visibility commands can operate on the selection. A clipboard snapshot is distinct from in-image duplication; append paste preserves existing boxes and selects only the new boxes. Both paste and in-image duplication preserve source coordinates without an automatic offset; paste still constrains coordinates to the target image bounds. Duplicates become selected.
- Previous-image annotation copy replaces the current boxes with copies from the previous image's session document, or its selected stored document if no session state exists. Paste, duplicate, and previous-image copy retain their completed results in history; Redo does not reread the clipboard or source image.

Pointer resolution uses current visible geometry and pointer position, independently of selection, modifiers, approach direction, and prior hover. Resolve the nearest eligible corner, then edge, then containing box interior. Corner and edge hit radii are measured in widget-logical screen pixels (11 and 5 respectively), independent of image zoom. Both hit areas shrink for very small boxes so an interior move target remains available; a corner drag follows its geometric diagonal. Distances equal within tolerance resolve to the topmost annotation layer.

Among overlapping interiors, strict containment chooses the innermost smallest box; partial overlap chooses the nearest boundary; remaining equality chooses the topmost box. Lower identical boxes remain selectable from the annotation list. Mouse press recomputes and locks the target until release or cancellation; crossing another box during a drag never retargets it. Explicitly hidden boxes cannot be hit; temporary overlap clipping preserves original hit geometry.

## Selection, hover, and label text

Selected boxes retain an opaque outline in their resolved label color and use a same-color fill at `30/255` opacity. Each selected box's visible label uses white text on a black background at about 60% opacity, small rounded corners, and about two pixels of padding. Hidden label text remains hidden.

Canvas hover replaces the complete target's normal outline with a short dashed outline of approximately 1.5 pixels in its label color. Dash and gap lengths are roughly equal; there is no solid underlay, extra fill, or label highlight. This applies to corner, edge, and interior targets, remains locked during a gesture, and is absent in Draw mode. Annotation-list hover is a presentation projection and never becomes a Canvas pointer target.

Label text normally sits above the box's top-left corner and moves inside when the Canvas edge leaves insufficient space. Its hit region is the actual rendered screen-space text bounds plus two pixels, independent of selection styling, scale, or display density. It exists only for visible text on a visible box and participates only in the label-edit gesture below.

## Direct single-box label editing

In Selection/Edit, an unmodified primary-button double-click on a visible box or its visible label replaces any multi-selection with that box and opens the shared single-box label editor. The box interior, outline, and adjustment handles are valid targets. Draw, Pan, Crop, and modifier-assisted double-clicks retain their own behavior.

The gesture recomputes ordinary geometry targeting first, even when unrelated label text overlaps that position. Only if no box is found does label-text targeting resolve strict containment by the smallest text region, partial overlap by nearest boundary, and equality by topmost annotation layer. Ordinary hover, clicks, Ctrl-selection, dragging, and context menus remain geometry-only.

Canvas, instance-button, F2, Edit-button, and `Ctrl+E` entry points share one pending annotation transaction from dialog opening through completion. Cancel and no-op confirmation create no history; a changed label creates one atomic edit and resolves its display color from the palette. Group double-click is a group-wide rename. The bilingual Help catalog documents the mouse gesture without adding a special cursor, label hover style, or extra Selection/Edit tooltip text.

## Label groups and instance strips

### Panel command placement

The annotation dock's movable title row contains the title, compact current-image totals, and global visibility, category-color, and list-option controls. Totals retain filter and hidden-selection information; elided header text exposes the complete summary in its tooltip and accessible name. Global visibility becomes available when annotations exist and applies to the whole image independently of selection.

Below the title, **Default category** and the category filter each occupy one aligned row. The default selector replaces the former checkbox and blank text field: **Choose each time** disables the fixed default, known categories can be chosen directly, and **Set fixed category…** opens the shared chooser for an arbitrary name. Cancel preserves the previous default. The fixed choice is window-local, survives navigation and candidate rescans, and remains selectable when unused; it never registers a workspace category until a box actually uses it. Fixed defaults retain precedence over the existing Single Class Mode behavior. No default-category choice is written to annotation data, history, or application settings.

Selection-dependent commands occupy a bottom bar shown only while boxes are selected. Single-box selection exposes category editing, duplication, deletion, and Difficult; multiple selection retains duplication/deletion and its complete selected count, including filtered-out boxes. Existing single-box capability and atomic history boundaries remain unchanged. Showing or hiding the bar changes the list's available height without moving the filter or its first row. The list, selector, and filter share the same horizontal margins.

### Rows and selection

The annotation list groups exact, case-sensitive labels. Groups exist only while they contain a box, and rows sort by case-insensitive natural label order with exact text as tie-breaker. A small opaque category-color bar precedes each ordinary text label. Instance buttons follow annotation-document order; their displayed ordinals may change after edits and are not stored identities.

Each row keeps its class name, total, and aggregate eye fixed while its complete instance strip scrolls horizontally. The shared class-name column fits content including bold selection text, may occupy nearly half a row, and always leaves at least one whole instance button. Elision is identical in every selection state and exposes full text on hover.

- An instance click selects only its box. A group-body click selects the whole group. Shift ranges follow global visual order: rows top-to-bottom, then buttons left-to-right, regardless of horizontal scrolling. A box is a point anchor; a group is an interval anchor that stays complete when the range extends either way. Multi-member group selection has no arbitrary active box and disables single-instance editing.
- Ordinary wheel input scrolls the list vertically; deliberate horizontal input scrolls the strip. Canvas selection minimally reveals the corresponding button. Canvas hover over an off-strip instance emphasizes the overflow direction without scrolling. Strip positions survive same-image view changes and reset on image change.
- Tab reaches the group list without visiting every instance. Arrows move among groups and visually ordered buttons; Space performs the corresponding selection gesture. Escape returns from an instance to its group, and F2 edits at the focused granularity. Focus movement reveals controls without creating hover.
- Renaming a group edits every member in one atomic change, merging into an existing destination group when applicable. Editing one instance moves only that box; empty source groups disappear. Group deletion is immediate and undoable, with label and count identified before execution.

Instance buttons use the theme background, an opaque category-color outline, and a readable theme-colored number. A visible selected button adds a `48/255` same-color fill and bold number; hover independently makes the outline dashed. Hidden buttons dim to about 45% and add a fine slash. Tooltips identify ordinal and geometry. The group label remains ordinary text rather than a category-colored capsule.

Group rows show no marker for no selected members, a small theme-accent dot for partial selection, and a slim inset accent marker plus bold text for complete selection. Hover adds a faint theme-gray background and approximately one-pixel neutral rounded inset border across the entire row, including the eye area; it preserves selection and instance styling.

Hovering a Canvas box previews only that box and its group row; hovering a group row previews every visible member. Neither changes selection, explicit visibility choices, scroll position, dirty state, or history. Hover alone does not trigger automatic overlap hiding; selected annotations continue to protect their boxes and displayed labels when that option is enabled. Hidden members remain absent from the Canvas.

## Filtering, visibility, and command scope

The case-insensitive group filter changes only shown rows. Selection outside the result remains active and is counted explicitly; list-focused Select All replaces it with all filtered results. Clearing the filter restores groups and prior strip positions. The summary reports current-image group and box counts, shown/total counts during filtering, and hidden selections. It excludes workspace candidate labels. An image with no boxes has a non-interactive empty explanation; a no-match result offers filter clearing without altering Canvas state.

Group isolation explicitly hides other groups on the Canvas; its inverse shows every group. The aggregate eye has all-visible, all-hidden, and mixed states. Clicking all-visible hides the group; clicking hidden or mixed shows it completely, without changing selection. Instance commands control individual or selected-box visibility; hidden boxes remain in strips and eligible for selection actions.

Right-clicking an unselected instance selects it; right-clicking a selected instance preserves the selection. Right-clicking a group body preserves selection while targeting that named group. Group-destructive commands name their affected count.

## Canvas context command surface

Secondary click constructs commands for the current pointer target. Blank-image click clears selection and offers Draw Box plus Paste Annotations only when the annotation clipboard is nonempty. An unselected box becomes the selection; a selected box retains the set and becomes active. Dismissing the menu preserves that result.

| Context | Commands |
| --- | --- |
| One selected box | Edit Label (default), clipboard Copy, in-image Duplicate, Hide/Show, then Delete in a final group |
| Multiple selected boxes | Copy, Duplicate, Hide/Show, Delete, each labeled with its count; no Edit |
| Draw | Secondary click cancels the pending box |
| Pan | No context menu |
| Crop | Undo Crop, Redo Crop, Apply Crop, Cancel; unavailable actions remain visible and disabled |

If any selected box is hidden, Show reveals the whole selection; otherwise Hide hides all of it. Delete is immediate and undoable. Blank menus have no off-pointer selection commands. Right-button dragging creates neither a shadow box nor a Copy Here/Move Here menu.

Menu and Shift+F10 open the same commands beside the active box, or at the visible Canvas center when nothing is selected. Native menu keyboard navigation, screen-edge placement, palette, focus, and high-contrast behavior remain intact. Local actions omit shortcut text, size from translated content and the native style, use coordinated operation icons for familiar commands, and distinguish Delete through wording and grouping.

## Near-duplicate box feedback

Two similarly sized boxes qualify when corresponding horizontal boundaries differ by at most `max(1 image pixel, 2% of the smaller width)` and vertical boundaries by at most `max(1 image pixel, 2% of the smaller height)`. Membership uses image coordinates and stays stable across zoom. Ordinary partial overlaps and materially larger enclosing boxes do not qualify.

Clusters are pairwise complete, with each box in at most one cluster. Ambiguous groups start from the pair with the smallest normalized boundary error, then annotation order breaks ties. A single-label cluster indicates likely duplication; mixed labels indicate category conflict. Findings do not validate or delete boxes and do not block saving, navigation, or export.

Each cluster has one fixed-screen-size Canvas marker outside its union bounds: an amber stacked-box symbol for duplication or magenta font-independent not-equal glyph for category conflict. Category conflict takes priority; the number always means total members, independent of visibility. A tooltip reports ordered label distribution and visible count, such as `cat ×2, dog ×1 · 2/3 visible`. Fully hidden clusters have no Canvas marker and stay discoverable in the list.

Markers normally sit outside the top-right union corner without a leader. Boundary or collision displacement adds one short leader; annotation geometry never moves. They brighten slightly on hover and are interactive only in Selection/Edit.

Activating a marker opens a non-modal member chooser without changing selection. Rows follow annotation order and show ordinal, label, and visibility, with geometry in tooltips. Click or Up/Down selects and focuses one member, replacing prior multi-selection; Space toggles visibility, F2 opens the shared label editor, Delete makes one undoable deletion, and Escape closes. There are no layer controls. Focus retains ordinary selected rendering for the chosen box, reduces peers' outlines to about 20% opacity, and hides peer labels. Closing, leaving the cluster, changing state, or Undo/Redo clears focus without restoring the prior selection.

Every involved instance has a 10-pixel risk corner; each affected group has one unnumbered dominant-risk icon using the same not-equal geometry. The 50-pixel group status column reserves a 16-pixel risk slot, three-pixel gap, and stable total slot even with no risk. Icon and total are centered. Risk activation opens the chooser; total activation retains group behavior. Category conflict wins the group icon while tooltips retain separate risk counts.

Dismissal suppresses a cluster on both surfaces for the workspace session. Member identity, geometry, or label changes invalidate it; selection and visibility do not. The list overflow command restores all ignored findings for the current image. No dismissal is saved in annotation formats. The bilingual Help catalog covers Canvas and list interactions.

## Verification entry points

Behavioral coverage lives in [Canvas tests](../../tests/canvas) and [annotation tests](../../tests/annotations). Rendering, targeting, group selection, near-duplicate grouping, and shared edit/history flows should be checked through their owning interfaces.
