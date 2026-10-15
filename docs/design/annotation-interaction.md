# Annotation Interaction

This is the current contract for selecting, targeting, and presenting annotation boxes and label groups. Terminology is in [CONTEXT.md](../../CONTEXT.md); [Canvas command surfaces](canvas-tool-rail.md) own tool placement and zoom, [annotation history](undo-redo-and-file-recovery.md) owns transactions and persistence, and the [session palette](session-label-color-palette.md) owns label colors.

## Pending box preview

Draw mode uses one reverse-screen crosshair across the entire visible Canvas, including margins outside the image. It follows the pointer before drawing and the constrained moving corner while drawing. Its horizontal and vertical arms share one mask; the center and crossings with the pending box invert once. The native small drawing cursor is hidden only within the Canvas, preserving ordinary pointers in category dialogs and other controls. Ctrl multi-selection temporarily uses its ordinary selection cursor; releasing Ctrl restores the Canvas crosshair. Leaving the Canvas or Draw mode clears it.

From placing the first corner through initial category confirmation, the preview emphasizes precise alignment and minimal obstruction of the target. Its appearance distinguishes unfinished creation from committed category-colored annotations.

The solid outline is approximately 1.5 logical screen pixels wide and follows the Windows reverse-screen cursor rule: fully covered displayed RGB channels become `255 - channel`. Gray backgrounds yield inverted gray, colored backgrounds yield complementary colors, and pure black and white interchange. Near-middle gray intentionally has little contrast with its inverse. This follows the reverse-screen mask behavior in [Microsoft's cursor documentation](https://learn.microsoft.com/en-us/windows/win32/menurc/using-cursors) and the raster operations described by [DrawIconEx](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-drawiconex).

The interior receives a subtle white overlay at approximately 6% opacity (`15/255`), without patterned fill or a connecting diagonal. This temporary Canvas presentation slightly brightens the enclosed image without modifying source pixels. It remains through initial category confirmation and disappears when creation is confirmed or canceled. The lift excludes the reverse-screen geometry, preserving the outline, guides, and marker's existing inversion. While geometry is being drawn, the first corner has one solid circular marker approximately four logical screen pixels in diameter. The moving corner is indicated by the crosshair. Canvas-wide horizontal and vertical alignment guides use crisp, device-aligned lines approximately one logical screen pixel wide and meet at the actual constrained corner, including image-boundary and square constraints. Marker and guides use the same reverse-screen treatment. These screen dimensions remain stable across image zoom and display density.

Reversal acts on the already displayed Canvas pixels, including display adjustments and any visible annotations underneath. Geometry is combined into one mask before applying white Difference composition, so overlapping outlines, guides, and markers reverse each pixel only once. Antialiasing affects boundary coverage only. There are no brightness thresholds, averaged sampling strips, or palette approximations; fixed portions remain stable when the endpoint moves or a partial repaint occurs. Image bounds clip the outline, interior lift, and starting marker; Canvas and repaint bounds clip the crosshair arms. View changes reproject a stationary pointer before repainting.

Width and height remain in the Canvas status strip and report the constrained preview geometry. Preview drawing uses that same floating-point geometry. It operates on rendered pixels even when the displayed pixmap resolution differs from the annotation coordinate space.

### Pending label confirmation

Completing geometry leaves a static reverse-screen outline and the subtle interior lift while the initial category chooser is open. Alignment guides and the start marker disappear. The new box remains visually pending throughout modal repaints and is excluded from ordinary category-colored shape drawing, so there is no intermediate green outline.

Confirming the category ends the preview and resolves the committed box's category color. Canceling removes the new box and its preview. Default-label creation follows the same boundary without displaying the chooser. Scene replacement and drawing cancellation clear temporary presentation state; they do not leave a ghost outline.

The Canvas tracks the pending label shape only as presentation state. Geometry finalization, scene membership, label assignment, annotation transactions, Undo/Redo, and persistence retain their existing ownership and commit sequence.

## Automatic overlap hiding

View → Auto-hide Parts Obscuring Annotation Targets (视图 → 自动隐藏遮挡目标的标注部分) is a checkable option, initially off, for temporarily clipping portions of other annotations under interaction targets. It applies around the drawing crosshair before the first corner, while drawing and through initial category confirmation, while annotations are selected, and while dragging or resizing. It has a distinct overlap-hiding icon and no keyboard shortcut. The user's choice persists across application launches; Reset All Settings restores the default off state.

Outside an active drawing crosshair, each visible selected annotation protects its box and visible label, including a selected label's background padding. These areas jointly mask only the covered portions of other annotations' outlines, fills, vertices, and text; every uncovered portion remains visible. All visible members of a selected group are protected together. Hovering a Canvas annotation or annotation-list instance/group retains its highlight but does not add protection or hide other annotations. Protected annotations are drawn complete above the clipped background in their original order, with a dragged annotation last. They do not clip one another. Manually hidden targets contribute no mask and stay hidden. Labels that are not displayed contribute no mask; label visibility follows the same rule as painting, including the label forced visible by near-duplicate focus.

Before the first corner and throughout geometry drawing, the crosshair center independently controls box and label presentation. Every explicitly visible existing box whose normalized geometric bounds contain the center has its entire outline, fill, and vertices temporarily suppressed. Every displayed label whose text/background bounds contain the center is independently hidden in full. Hiding a box does not hide an unrelated label outside the center, and hiding a label does not hide its box unless the center also lies in that box. Multiple containing boxes or labels are all suppressed. Boundary contact counts; labels use the same displayed geometry as painting, including selected background padding. Components restore as soon as the center leaves their original bounds. The source image and the unified crosshair remain visible. This drawing intent takes priority over selection protection. Edit-mode hover remains highlight-only.

Drawing suppression uses only the constrained crosshair center, including reverse drawing, image-boundary constraints, and square constraints; neither the long crosshair arms nor the rest of the pending rectangle suppress other annotations during geometry drawing. Point containment is evaluated in image coordinates, so zoom, display density, and viewport changes do not introduce a fixed clearance radius or width. Opening the initial category chooser ends center-based suppression and returns to the pending rectangle's local clipping until creation completes or is canceled. Ctrl multi-selection and panning suspend idle center-based suppression. Leaving the Canvas before starting a box restores affected components; scene replacement clears the tracked pointer. Existing visible selections can protect annotations in Draw mode when no drawing crosshair or pending drawing is present; protected shapes are painted separately above the cached background.

Targets update immediately on selection, visibility, geometry, zoom, and label-display changes. Selection protection persists after pointer departure or drag release until deselection. Clearing selection restores other annotations even if the pointer remains over a previously selected target. Finishing or canceling creation/dragging returns to protection derived from the current selection or active drawing crosshair. Mode and scene changes discard their transient targets; turning the option off restores explicitly visible background portions immediately.

Automatic overlap hiding is a Canvas presentation filter, independent of explicit visibility. It does not change annotations, history, list eye states, or the user's manual visibility choices. Target resolution continues to use original explicitly visible geometry, so temporary clipping cannot make a target unreachable or cause hover flicker.

Near-duplicate Canvas markers disappear only when every explicitly visible member's box and displayed label are suppressed, considering both center-based component hiding and local clipping. Protected or partially clipped members retain their marker. The mask and protected set are computed once for each marker layout. Cluster membership, total counts, and annotation-list risk feedback stay unchanged.

Draw mode retains a transparent annotation layer for the visible viewport. Box and label visibility are cached separately; changes damage the affected annotation bounds and intersecting peers while unrelated annotations retain their cached pixels. Local clipping for selected targets or initial label confirmation is applied during composition. Protected targets are excluded from the background cache and painted complete afterward. The layer tracks geometry, appearance, selection, explicit visibility, and component presentation; zoom, display density, viewport changes, scene replacement, and annotation order changes rebuild it. Source-image display adjustments remain beneath the transparent layer and the reverse-screen preview remains above it. Leaving Draw mode releases the layer. Its allocation is capped at 64 MiB; oversized captures fall back to ordinary painting with the same box/label visibility and clipping. Pixel comparisons cover cached/direct rendering, separate box and label containment, nested boxes, constrained endpoints, selected targets, and restoration when protection ends.

## Selection and pointer targets

Every newly opened or navigated image starts with an empty annotation selection. Canvas and annotation-list selection stay synchronized; file selection is independent.

- Holding Ctrl enters temporary multi-selection with a crosshair. A click toggles one box; a dragged selection region replaces the selection with fully contained boxes. The region is dashed and lightly translucent. After its drag threshold, single-box hover is suppressed until release recomputes the pointer target.
- Ctrl suppresses resize cursors and enlarged corners while retaining complete-box hover. Releasing it restores ordinary editing without clearing selection.
- Ordinary geometry edits require one selected box. Copy, duplicate, delete, and explicitly scoped visibility commands can operate on the selection. A clipboard snapshot is distinct from in-image duplication; append paste preserves existing boxes and selects only the new boxes. Duplicates are slightly offset and become selected.
- Previous-image annotation copy replaces the current boxes with copies from the previous image's session document, or its selected stored document if no session state exists. Paste, duplicate, and previous-image copy retain their completed results in history; Redo does not reread the clipboard or source image.

Pointer resolution uses current visible geometry and pointer position, independently of selection, modifiers, approach direction, and prior hover. Resolve the nearest eligible corner, then edge, then containing box interior. Corner hit areas shrink for very small boxes so an interior move target remains available; a corner drag follows its geometric diagonal. Distances equal within tolerance resolve to the topmost annotation layer.

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

The annotation list groups exact, case-sensitive labels. Groups exist only while they contain a box, and rows sort by case-insensitive natural label order with exact text as tie-breaker. Instance buttons follow annotation-document order; their displayed ordinals may change after edits and are not stored identities.

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
