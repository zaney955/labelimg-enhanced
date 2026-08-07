# Image Tools Workspace

Design status: approved on 2026-08-07. The planned capabilities in this document are not implementation authorization and remain unimplemented until separately approved and validated.

## Outcome

LabelImg Enhanced provides a built-in Image menu and two explicit image-tool surfaces. Pixel-only operations use the shared modal image-tools workspace; geometry-changing operations may use a dedicated Canvas mode when direct spatial interaction is essential. The first tools remove red and yellow rectangular frame overlays and crop the current image. Both share the same preparation, commit, and recovery principles without mixing committed image processing into annotation Undo.

## Command surfaces

The Image menu is the complete catalog for annotation-preparation image capabilities. The main Tools toolbar is a deliberately smaller set of frequent shortcuts, not a second catalog: a tool remains fully available from the Image menu even when it has no toolbar button. Starting a command delegates its interaction to the shared modal workspace or to a tool-specific Canvas mode according to whether direct spatial manipulation is essential.

Toolbar inclusion is therefore a separate product decision from feature inclusion. A command earns a toolbar shortcut only when it is used frequently on the current image, has a distinct recognizable icon, and does not require the toolbar itself to expose parameters or results. Recovery, batch selection, diagnostics, and infrequent specialist actions remain menu or workspace capabilities.

The planned main-toolbar image entries are Crop plus Rotate and Flip split buttons. Clicking Rotate immediately rotates the current image clockwise 90 degrees; its menu also offers counter-clockwise 90-degree and 180-degree rotation. Clicking Flip immediately flips the current image horizontally; its menu also offers vertical flip. Resize, Adjust Image, Check Image Quality, specialized repair, and recovery remain outside the main toolbar.

## Approved capability boundary

This section records the approved product scope, not the current implementation status. A capability remains planned until its code and validation are complete.

Geometry preparation includes the existing crop plus clockwise and counter-clockwise 90-degree rotation, 180-degree rotation, horizontal and vertical flip, and resize. Every operation transforms annotations with the image and follows the geometry synchronization invariant. Arbitrary-angle rotation is excluded while annotations remain axis-aligned rectangles because its box semantics would be ambiguous.

Pixel correction includes brightness and contrast, Gamma as an advanced control, automatic contrast, and grayscale conversion. These operations use preview and recoverable commit. Saturation, hue, white balance, sharpening, stylistic filters, and beautification are outside the approved scope so the Image menu remains focused on annotation preparation rather than general photo editing.

Image quality checking is one analysis-only capability covering unreadable or corrupt files, low resolution, aspect-ratio anomalies, blur, excessive darkness, and overexposure. Findings appear as file-list state and support filtering; checking never modifies image files automatically. Duplicate and near-duplicate discovery is a dataset-level concern and does not belong in the Image menu.

Specialized repair currently includes red and yellow frame removal. New specialized repairs require representative real samples and explicit acceptance criteria before they enter the capability catalog. Manual region blur or mosaic, watermark removal, background removal, denoising, and super-resolution are not planned speculatively.

The Image menu presents Crop first, followed by a Rotate and Flip submenu containing every quick transform, Transform Image… for previewed or batch geometry work, Adjust Image…, Check Image Quality…, a Specialized Repair submenu containing Remove Red/Yellow Frames…, and Undo Last Image Processing…. This menu remains the complete catalog even when toolbar shortcuts exist.

## Target selection

Every session begins with an explicit target set. The current Canvas image is always the safe default. When the file list contains multiple selected images, a batch-capable workspace tool offers a separate “Selected images (N)” scope that the user must choose explicitly; opening a tool never infers the complete directory as a batch. Crop is current-image-only because its region is specific to one image's content and coordinate space.

The target list remains visible in the workspace. Results are prepared in the background, each image can be inspected, and any image can be excluded before commit. Images with no selected repair candidates are automatically excluded and retain their exact original bytes.

Planned rotation, flip, and resize operations use the same explicit current-image or selected-images target rule. A selected geometry batch preflights every image and associated annotation resource, then commits the complete target set atomically; any failure leaves the whole batch unchanged. Crop remains current-image-only.

## Workspace and history

The pixel-tool workspace is modal and suspends annotation interaction while open. An unresolved drawing, vertex drag, edge drag, or other pending annotation gesture blocks entry; already committed but unsaved annotations are allowed and remain untouched. Crop instead uses a temporary Canvas mode that keeps annotations visible but non-interactive and resolves unsaved annotation changes before entry.

Multiple pixel-tool steps may be composed before one workspace commit. The workspace owns a transient Undo/Redo sequence: Ctrl+Z and Ctrl+Y operate on image-tool steps only while the workspace is active. Geometry-changing Canvas modes keep their own transient adjustment history and commit separately. The main annotation workbench keeps its existing annotation-only Undo/Redo contract.

Settings return to safe defaults whenever the workspace opens. They are not persisted across invocations, workspaces, or launches.

## Planned geometry transforms

Image → Transform Image… provides the preview workspace for rotation, flip, and proportional resize. It supports the current image or explicitly selected images and requires an explicit Apply action. Specific menu commands may enter that shared workspace with their corresponding operation preselected.

Rotation and flip additionally provide quick transforms for the current image. Rotate clockwise 90 degrees, rotate counter-clockwise 90 degrees, rotate 180 degrees, flip horizontally, and flip vertically skip the workspace and confirmation, then immediately transform the image and annotations and commit them atomically. Each invocation creates its own recoverable image-processing entry. Quick transforms are disabled during a pending annotation gesture, unresolved annotation conflict, or active crop session; selected files never become an implicit quick-transform target.

Quick transforms have no keyboard shortcuts. They are invoked only through the Image menu or the Rotate and Flip toolbar split buttons, avoiding additional Canvas single-key commands. If the current annotation document has committed but unsaved changes, the existing Save, Discard, or Cancel flow resolves them before transformation; the tool never saves them implicitly. Cancel leaves the image unchanged.

## Planned resize

Resize performs proportional resampling only. Aspect ratio is locked, and the user may enter a target width, target height, or percentage; changing any one derives the others. An automatic interpolation policy chooses an appropriate resampler for reduction or enlargement. Enlargement is allowed only after an explicit warning that it adds no source detail. Forced stretching and Letterbox padding are excluded because they belong to training or export preprocessing rather than in-place annotation-source preparation.

## Planned pixel correction

Image → Adjust Image… opens one shared modal workspace for brightness, contrast, advanced Gamma, automatic contrast, and grayscale conversion. The current image is the safe default and explicitly selected images are an optional batch target. Corrections can be composed, previewed, temporarily undone or redone, and committed once through the existing recoverable pixel-only replacement path. No correction receives an independent toolbar button, and every invocation starts from safe control defaults.

## Planned image quality checking

Image → Check Image Quality… explicitly offers the current image, selected images, or every image in the current annotation workspace; the workspace-wide scope is the default. Checking runs in the background, is cancellable, and reports findings by problem type and severity without changing images or annotations.

Findings are cached under the application configuration directory and keyed by file path, content fingerprint, and the check policy that produced them. A changed file or changed check policy invalidates the affected cached result. The file list displays and filters those derived findings without conflating them with annotation review state, and no cache or sidecar is written into image or annotation directories.

One image may retain multiple findings. Unreadable or corrupt content is an error; low resolution, aspect-ratio anomalies, blur, excessive darkness, and overexposure are severity-ranked warnings. Findings never change the separate Unreviewed, Review Required, or Verified annotation review state. An unreadable image cannot enter the normal Canvas, while warnings do not block annotation.

Every check starts with a visible Standard policy. Advanced controls may override its thresholds for that scan, and the exact effective policy is stored with the results; an override does not silently become the next scan's default. Named policies are outside the first release.

The file list shows quality badges and supports finding and severity filters. An on-demand non-modal Image Quality panel summarizes counts, lists details, and navigates to affected images without permanently occupying the single-image annotation workbench.

The first quality engine is deterministic, explainable, and local; it neither downloads nor loads an AI model. Every finding reports the measured value, effective threshold, and reason. Readability comes from actual decoding, low resolution from image dimensions, aspect anomalies from both absolute extremes and workspace-distribution outliers, blur from a resolution-normalized sharpness metric, and excessive darkness or exposure from luminance-distribution proportions. Standard thresholds are calibrated against test samples during implementation rather than becoming hidden product assumptions.

The Image menu and Image Quality panel can recheck the current image, selected images, or current workspace and can clear quality findings. A changed file or changed check policy immediately becomes Unchecked instead of displaying a stale finding. Clearing results removes only the application-owned cache and never changes image or annotation files.

## Geometry synchronization invariant

A geometry-changing image-processing commit or recovery is not complete when its file replacements alone succeed. Before LabelImg reports success or re-enables drawing, annotation editing, saving, Undo/Redo, or navigation, it synchronously projects the resulting or restored dimensions into the decoded current image and Canvas bounds, annotation shapes and label-list rows, the active in-memory annotation document and clean baseline, annotation-history snapshots or their replacement baseline, and every retained per-image workspace cache and resource fingerprint. The candidate-label vocabulary contains class names rather than geometry and is therefore outside this size synchronization.

Every one of those projections must describe the same image-annotation coordinate space. For a non-current image, processing or recovery must rebase or discard any retained geometry-dependent in-memory state before that state can be reused. LabelImg must never expose an editable mixture of old and new dimensions or defer correction until a later save, reload, or navigation. If synchronous projection cannot be completed, the operation remains unsuccessful and must roll back or keep editing blocked while reporting the failure.

## Crop current image

Image → Crop… and the dedicated toolbar action enter crop mode for the current Canvas image; `C` does the same only while the Canvas owns keyboard interaction. Crop is unavailable without an open image and never adopts the file-list selection as an implicit batch. The action remains visibly checked while active. Pressing `C` again does nothing; `Esc` cancels and Canvas-focused `Enter` applies.

Crop mode suspends annotation editing and displays a dimmed outside region. Entering or leaving crop mode never changes the Canvas or viewport geometry. The user drags on the Canvas to create a crop region, then moves it from the interior or resizes it from any point along one of the four complete edges; the corner hit zones resize both axes and take priority over edge hit zones, which take priority over interior movement. The edge and corner hit zones retain a fixed screen-pixel tolerance at every zoom level. Dragging outside an existing region replaces it.

A floating tool-options panel is overlaid at the top center of the Canvas viewport without participating in application layout. It can be dragged anywhere within the viewport to avoid important image content, remains stationary until the crop session ends, and returns to the top center the next time crop mode starts. The panel exposes free, original, 1:1, 4:3, and 16:9 ratios; integer X, Y, width, and height fields; and explicit Apply Crop and Cancel actions. Before a crop region exists, X and Y are read-only live zero-based image coordinates for the pointer, retain the last valid in-image position after the pointer leaves, and width and height show zero and remain disabled. Once a region exists, all four fields switch to editable crop-region geometry. Enter in a numeric field accepts that value and returns focus to the Canvas without applying. Direction keys move the region by one image pixel and Shift plus a direction key moves it by ten.

Free ratio is the default. A locked-ratio corner drag keeps the opposite corner fixed; an edge drag changes the perpendicular dimension around the region center. Width and height inputs update each other while locked. Switching ratios preserves the region center and fits the adjusted region within image bounds. A crop region is always an integer, in-bounds rectangle of at least 1 by 1 pixel. No region and a full-image no-op both disable Apply.

Annotations remain visible but cannot be edited in crop mode. The region previews their resulting geometry: contained boxes translate to the new origin, intersecting boxes clip to the new bounds whenever a positive-area intersection remains, and boxes outside the region disappear. There is no hidden visibility threshold. Applying a crop that clips or removes annotations first reports both counts and asks for confirmation. Crop-region creation and adjustment have their own transient Ctrl+Z and Ctrl+Y/Ctrl+Shift+Z history, which is discarded on cancel and never enters annotation history.

Before crop mode starts, unresolved annotation changes use the existing save, discard, or cancel workflow. Applying crop atomically commits the resized image and transformed annotation resources; after success, the geometry synchronization invariant establishes those annotations and the resized image as one new clean in-memory baseline before editing resumes, and ordinary annotation Undo cannot return to the pre-crop coordinate space. Image-processing recovery restores the original image and annotations together and synchronously establishes their restored dimensions as the replacement in-memory baseline. If the processed image, a dedicated annotation resource, or the affected record in a shared CreateML collection has changed, recovery refuses the complete unit rather than restoring only one side. A shared CreateML document may contain unrelated later edits; recovery restores only the affected image record and preserves those unrelated valid changes.

Crop preserves the zoom factor, translates the viewport by the crop origin, and clamps it to the new image bounds. Selection survives for retained annotation boxes and drops removed boxes. Leaving the image, switching tools, or closing while a crop region has been created offers Apply Crop, Discard Crop, or Cancel; a session with no region exits silently. Crop and pixel-only image tools commit as separate ordered operations rather than composing in one uncommitted session.

## Remove red and yellow frames

The tool treats saturated red and yellow pixels as candidates, using the reference HSV ranges from `remove_red_yellow_boxes.py`, but color alone is insufficient. A candidate must also resemble a rectangular outline under the selected conservative, standard, or loose geometry policy. Solid colored regions and ordinary red or yellow objects are not frame overlays.

The default controls select red and yellow, use standard detection strength, and allow Original, Result, and Repair Mask preview modes. Original and Result identify each candidate with a fixed 22-pixel numbered ring anchored just inside its top-left corner; Repair Mask remains a pure pixel preview. The number matches the candidate list. Included candidates use a theme-accent ring and number, while excluded candidates use a neutral ring and number. Candidate markers never use red or yellow, so they cannot be mistaken for image content.

The numbered rings are non-pixel UI overlays: they are painted after the preview image and never enter the preview base pixmap, committed image, or annotations. A candidate can be toggled only through its ring or its candidate-list row; the rest of its detected rectangle is not an invisible click target. Hovering a ring shows its number, detected color, current inclusion state, and click action without changing selection. Badges remain 22 screen pixels across while zooming or resizing, stay inside image edges, and move deterministically when their preferred positions collide. Excluding a candidate retains its number for the current analysis; changing detection options may re-run analysis and renumber candidates in top-to-bottom, left-to-right order.

Each detected frame is separately selectable so a false positive can be excluded without excluding the whole image. The first release does not include a brush, freehand mask, or manual missed-frame creation.

Repair uses Telea inpainting with a default radius of 3. Advanced controls expose the inpaint radius, bounded halo dilation, and whole-image near-grayscale normalization. Halo dilation defaults to zero. Whole-image grayscale normalization is explicit and defaults off; otherwise only the frame repair region may change color.

## Supported files and metadata

The first release accepts 8-bit JPEG, PNG, and BMP images. Unsupported formats and bit depths are reported before any commit and remain unchanged.

Pixel-only output retains the source path, filename, format, pixel dimensions, orientation behavior, alpha channel where applicable, and valid EXIF, ICC, and DPI metadata. Geometry-changing output retains the same compatible identity and metadata while replacing pixel dimensions with the explicit tool result. JPEG encoding reuses the source quantization and subsampling characteristics when available. An image that has no selected repair region is never re-encoded.

## Commit

Apply in the modal pixel-tool workspace closes it after success and refreshes the current Canvas image while preserving annotation content, selection, zoom, and pan. Geometry-changing Canvas tools instead apply their documented annotation transformation and geometry synchronization contract. The complete selected target set is prepared and validated before files change. Preparation is cancellable and leaves no user files behind. The short commit phase is not cancellable.

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

Automated validation covers red, yellow, mixed, no-frame, solid-color negative, per-candidate exclusion, grayscale normalization opt-in, alpha preservation, metadata retention, exact no-op bytes, format rejection, transient Undo/Redo, cancellable preparation, atomic commit rollback, selectable atomic recovery, external-change conflicts, bilingual UI, and preservation of Canvas annotation/view state. Crop coverage additionally includes route-independent cursor ownership, invariant Canvas geometry on entry and exit, draggable floating controls, live pre-region pointer coordinates, complete-edge hit testing at multiple zoom levels, integer region geometry, ratio locking, mouse and keyboard adjustment, focus-safe shortcuts, RGB/grayscale/RGBA output, resized metadata, annotation translation/clipping/removal, Pascal VOC/YOLO/CreateML projection, joint rollback and recovery, synchronous dimension projection into the Canvas, label list, active document, clean baseline, histories and caches, rejection of mixed-coordinate editable state, and post-crop viewport and selection state.

The three JPEG files under `C:\Users\GW-LIYU\Downloads\red_box` are the initial real-data acceptance set for red-frame detection and repair. Yellow, mixed-color, and negative-object evidence is synthetic until representative real files are supplied; validation reports must preserve that distinction.
