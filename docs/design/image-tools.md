# Image Tools Workspace

## Outcome

LabelImg Enhanced provides a built-in Image menu and two explicit image-tool surfaces. Pixel-only operations use the shared modal image-tools workspace; geometry-changing operations may use a dedicated Canvas mode when direct spatial interaction is essential. The first tools remove red and yellow rectangular frame overlays and crop the current image. Both share the same preparation, commit, and recovery principles without mixing committed image processing into annotation Undo.

## Target selection

Every session begins with an explicit target set. The current Canvas image is always the safe default. When the file list contains multiple selected images, a batch-capable workspace tool offers a separate “Selected images (N)” scope that the user must choose explicitly; opening a tool never infers the complete directory as a batch. Crop is current-image-only because its region is specific to one image's content and coordinate space.

The target list remains visible in the workspace. Results are prepared in the background, each image can be inspected, and any image can be excluded before commit. Images with no selected repair candidates are automatically excluded and retain their exact original bytes.

## Workspace and history

The pixel-tool workspace is modal and suspends annotation interaction while open. An unresolved drawing, vertex drag, edge drag, or other pending annotation gesture blocks entry; already committed but unsaved annotations are allowed and remain untouched. Crop instead uses a temporary Canvas mode that keeps annotations visible but non-interactive and resolves unsaved annotation changes before entry.

Multiple image-tool steps may be composed before commit. The workspace owns a transient Undo/Redo sequence: Ctrl+Z and Ctrl+Y operate on image-tool steps only while the workspace is active. The main annotation workbench keeps its existing annotation-only Undo/Redo contract.

Settings return to safe defaults whenever the workspace opens. They are not persisted across invocations, workspaces, or launches.

## Crop current image

Image → Crop… and the dedicated toolbar action enter crop mode for the current Canvas image; `C` does the same only while the Canvas owns keyboard interaction. Crop is unavailable without an open image and never adopts the file-list selection as an implicit batch. The action remains visibly checked while active. Pressing `C` again does nothing; `Esc` cancels and Canvas-focused `Enter` applies.

Crop mode suspends annotation editing and displays a dimmed outside region. The user drags on the Canvas to create a crop region, then moves it from the interior or resizes it from four edge and four corner handles. Dragging outside an existing region replaces it. A temporary control bar above the Canvas exposes free, original, 1:1, 4:3, and 16:9 ratios; integer X, Y, width, and height fields; and explicit Apply Crop and Cancel actions. Enter in a numeric field accepts that value and returns focus to the Canvas without applying. Direction keys move the region by one image pixel and Shift plus a direction key moves it by ten.

Free ratio is the default. A locked-ratio corner drag keeps the opposite corner fixed; an edge drag changes the perpendicular dimension around the region center. Width and height inputs update each other while locked. Switching ratios preserves the region center and fits the adjusted region within image bounds. A crop region is always an integer, in-bounds rectangle of at least 1 by 1 pixel. No region and a full-image no-op both disable Apply.

Annotations remain visible but cannot be edited in crop mode. The region previews their resulting geometry: contained boxes translate to the new origin, intersecting boxes clip to the new bounds whenever a positive-area intersection remains, and boxes outside the region disappear. There is no hidden visibility threshold. Applying a crop that clips or removes annotations first reports both counts and asks for confirmation. Crop-region creation and adjustment have their own transient Ctrl+Z and Ctrl+Y/Ctrl+Shift+Z history, which is discarded on cancel and never enters annotation history.

Before crop mode starts, unresolved annotation changes use the existing save, discard, or cancel workflow. Applying crop atomically commits the resized image and transformed annotation resources; after success, those annotations form a new clean baseline and ordinary annotation Undo cannot return to the pre-crop coordinate space. Image-processing recovery restores the original image and annotations together. If the processed image, a dedicated annotation resource, or the affected record in a shared CreateML collection has changed, recovery refuses the complete unit rather than restoring only one side. A shared CreateML document may contain unrelated later edits; recovery restores only the affected image record and preserves those unrelated valid changes.

Crop preserves the zoom factor, translates the viewport by the crop origin, and clamps it to the new image bounds. Selection survives for retained annotation boxes and drops removed boxes. Leaving the image, switching tools, or closing while a crop region has been created offers Apply Crop, Discard Crop, or Cancel; a session with no region exits silently. Crop and pixel-only image tools commit as separate ordered operations rather than composing in one uncommitted session.

## Remove red and yellow frames

The tool treats saturated red and yellow pixels as candidates, using the reference HSV ranges from `remove_red_yellow_boxes.py`, but color alone is insufficient. A candidate must also resemble a rectangular outline under the selected conservative, standard, or loose geometry policy. Solid colored regions and ordinary red or yellow objects are not frame overlays.

The default controls select red and yellow, use standard detection strength, and allow Original, Result, and Repair Mask preview modes. Original and Result identify each candidate with a fixed 22-pixel numbered ring anchored just inside its top-left corner; Repair Mask remains a pure pixel preview. The number matches the candidate list. Included candidates use a theme-accent ring and number, while excluded candidates use a neutral ring and number. Candidate markers never use red or yellow, so they cannot be mistaken for image content.

The numbered rings are non-pixel UI overlays: they are painted after the preview image and never enter the preview base pixmap, committed image, or annotations. A candidate can be toggled only through its ring or its candidate-list row; the rest of its detected rectangle is not an invisible click target. Hovering a ring shows its number, detected color, current inclusion state, and click action without changing selection. Badges remain 22 screen pixels across while zooming or resizing, stay inside image edges, and move deterministically when their preferred positions collide. Excluding a candidate retains its number for the current analysis; changing detection options may re-run analysis and renumber candidates in top-to-bottom, left-to-right order.

Each detected frame is separately selectable so a false positive can be excluded without excluding the whole image. The first release does not include a brush, freehand mask, or manual missed-frame creation.

Repair uses Telea inpainting with a default radius of 3. Advanced controls expose the inpaint radius, bounded halo dilation, and whole-image near-grayscale normalization. Halo dilation defaults to zero. Whole-image grayscale normalization is explicit and defaults off; otherwise only the frame repair region may change color.

## Supported files and metadata

The first release accepts 8-bit JPEG, PNG, and BMP images. Unsupported formats and bit depths are reported before any commit and remain unchanged.

The output retains the source path, filename, format, pixel dimensions, orientation behavior, alpha channel where applicable, and valid EXIF, ICC, and DPI metadata. JPEG encoding reuses the source quantization and subsampling characteristics when available. An image that has no selected repair region is never re-encoded.

## Commit

Apply closes the workspace after success and refreshes the current Canvas image while preserving annotation content, selection, zoom, and pan. The complete selected target set is prepared and validated before files change. Preparation is cancellable and leaves no user files behind. The short commit phase is not cancellable.

Commit stages every encoded result beside its source, preflights recoverable system-trash support, rechecks source fingerprints, moves every original to recoverable trash, and atomically installs every result. Any failure rolls the complete batch back. A system that cannot guarantee an actionable recovery identity cannot commit an in-place image operation.

## Recovery

Committed image processing does not enter annotation Undo or a tool's transient adjustment history. Image → Undo Last Image Processing… opens the latest committed operation. A single-image operation uses a confirmation; a multi-image batch lists every still-recoverable image and defaults to selecting all. A geometry-changing operation restores each image and its annotations as an indivisible recovery unit.

The user may restore an explicit subset. That selected subset restores atomically after verifying that each dedicated processed file still matches its committed fingerprint. For a shared CreateML file, the affected image record must still match the committed result, while unrelated records may have changed and are preserved. Unselected images keep their processed files and recovery eligibility. Earlier entries remain available through File → Recent File Operations….

One-click recovery is scoped to the current image workspace and clears when the workspace changes or the application exits. Originals remain in the system trash for manual recovery afterward. Image-processing recovery never overwrites an externally changed processed file.

## Menu ownership

- Edit owns annotation Undo and Redo.
- Image owns image-tool commands and committed image-processing recovery.
- File owns the broader recent-file-operations recovery center.
- No top-level Undo menu or mixed global history is introduced.

## Concurrency and failure reporting

Preview work runs away from the GUI thread and reports per-image queued, processing, ready, no-frame, unsupported, failed, or excluded status. Closing or canceling the workspace cancels pending preparation and removes temporary results. Commit begins only when every included image is ready.

Failures identify the affected image and phase without exposing untranslated application text. Verbatim operating-system diagnostics remain unchanged inside a localized explanation, following the application-language contract.

## Validation

Automated validation covers red, yellow, mixed, no-frame, solid-color negative, per-candidate exclusion, grayscale normalization opt-in, alpha preservation, metadata retention, exact no-op bytes, format rejection, transient Undo/Redo, cancellable preparation, atomic commit rollback, selectable atomic recovery, external-change conflicts, bilingual UI, and preservation of Canvas annotation/view state. Crop coverage additionally includes integer region geometry, ratio locking, mouse and keyboard adjustment, focus-safe shortcuts, RGB/grayscale/RGBA output, resized metadata, annotation translation/clipping/removal, Pascal VOC/YOLO/CreateML projection, joint rollback and recovery, and post-crop viewport and selection state.

The three JPEG files under `C:\Users\GW-LIYU\Downloads\red_box` are the initial real-data acceptance set for red-frame detection and repair. Yellow, mixed-color, and negative-object evidence is synthetic until representative real files are supplied; validation reports must preserve that distinction.
