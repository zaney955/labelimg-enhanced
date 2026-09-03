# Annotation Interaction

This is the current contract for selecting, targeting, and presenting annotation boxes and label groups. Terminology is in [CONTEXT.md](../../CONTEXT.md); [Canvas command surfaces](canvas-tool-rail.md) own tool placement and zoom, [annotation history](undo-redo-and-file-recovery.md) owns transactions and persistence, and the [session palette](session-label-color-palette.md) owns label colors.

## Pending box preview redesign (draft)

The agreed scope is the new-box preview between placing its first corner and completing its geometry. The agreed visual goals are clear boundaries, precise alignment with image content, and minimal obstruction of the target. This is a design draft, with agreed choices and remaining questions distinguished below; it does not describe implemented behavior.

The current preview paints corner dots, a diagonal between the two defining corners, and a rectangle with a diagonal-pattern fill. The rectangle outline does not explicitly compensate for Canvas zoom, unlike the diagonal and dots. Width and height are already shown in the Canvas status strip using constrained preview geometry. The full-image crosshair is shown before the first corner and is cleared when the pending preview moves.

Agreed presentation:

- Use a high-contrast grayscale outline whose color adapts to the background, replacing the proposed fixed green. The outline stays opaque and approximately 1.5 logical screen pixels wide across zoom levels. The grayscale contrast treatment supersedes the proposed fixed dark underlay; its exact behavior is still under discussion.
- Keep the interior transparent and remove both the diagonal-pattern fill and the line connecting the defining corners.
- Use a solid circular start marker instead of the proposed hollow circle. The moving endpoint remains indicated by the crosshair.
- Continue the thin full-image horizontal and vertical alignment guides during the preview. Their intersection follows the actual constrained preview corner, including image-boundary and square constraints.
- Keep width and height in the existing Canvas status strip.

Open decisions are how the outline adapts when one edge crosses both light and dark content, and whether the alignment guides and start marker share the adaptive grayscale treatment. The existing selection, hover, and completed-box presentation contracts remain outside this redesign's scope.

## Selection and pointer targets

Every newly opened or navigated image starts with an empty annotation selection. Canvas and annotation-list selection stay synchronized; file selection is independent.

- Holding Ctrl enters temporary multi-selection with a crosshair. A click toggles one box; a dragged selection region replaces the selection with fully contained boxes. The region is dashed and lightly translucent. After its drag threshold, single-box hover is suppressed until release recomputes the pointer target.
- Ctrl suppresses resize cursors and enlarged corners while retaining complete-box hover. Releasing it restores ordinary editing without clearing selection.
- Ordinary geometry edits require one selected box. Copy, duplicate, delete, and explicitly scoped visibility commands can operate on the selection. A clipboard snapshot is distinct from in-image duplication; append paste preserves existing boxes and selects only the new boxes. Duplicates are slightly offset and become selected.
- Previous-image annotation copy replaces the current boxes with copies from the previous image's session document, or its selected stored document if no session state exists. Paste, duplicate, and previous-image copy retain their completed results in history; Redo does not reread the clipboard or source image.

Pointer resolution uses current visible geometry and pointer position, independently of selection, modifiers, approach direction, and prior hover. Resolve the nearest eligible corner, then edge, then containing box interior. Corner hit areas shrink for very small boxes so an interior move target remains available; a corner drag follows its geometric diagonal. Distances equal within tolerance resolve to the topmost annotation layer.

Among overlapping interiors, strict containment chooses the innermost smallest box; partial overlap chooses the nearest boundary; remaining equality chooses the topmost box. Lower identical boxes remain selectable from the annotation list. Mouse press recomputes and locks the target until release or cancellation; crossing another box during a drag never retargets it. Hidden boxes cannot be hit.

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

Hovering a Canvas box previews only that box and its group row; hovering a group row previews every visible member. Neither changes selection, visibility, scroll position, dirty state, or history. Hidden members remain absent from the Canvas.

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
