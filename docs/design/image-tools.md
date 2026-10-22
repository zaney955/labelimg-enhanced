# Image Tools Workspace

Current image-tool contract. [ADR 0013](../adr/0013-commit-image-processing-as-recoverable-atomic-replacement.md) records atomic replacement and recovery, [ADR 0014](../adr/0014-ship-image-tools-with-the-core-runtime.md) records core-runtime ownership, and [ADR 0015](../adr/0015-commit-geometry-changing-image-tools-with-annotations.md) records joint image/annotation geometry commits.

## Outcome

Pixel-only operations use a modal image-tools workspace; geometry-changing operations may use a dedicated Canvas mode when direct spatial interaction is essential. Both share preparation, commit, and recovery rules without mixing committed image processing into annotation Undo.

## Command surfaces

The Image menu is the complete capability catalog. [Menu ownership](menu-information-architecture.md) separates annotation history in Edit, image processing in Image, and the broader recovery center in File. [Canvas command surfaces](canvas-tool-rail.md) define Crop and Rotate/Flip placement and default clicks. Resize, Adjust Image, quality checks, specialized repair, batch selection, and recovery remain menu or workspace capabilities. A quick action requires frequent current-image use and a recognizable icon without inline parameters or results.

## Approved capability boundary

Geometry preparation includes the existing crop plus clockwise and counter-clockwise 90-degree rotation, 180-degree rotation, horizontal and vertical flip, and resize. Every operation transforms annotations with the image and follows the geometry synchronization invariant. Arbitrary-angle rotation is excluded while annotations remain axis-aligned rectangles because its box semantics would be ambiguous.

Pixel correction includes brightness and contrast, Gamma as an advanced control, one-shot automatic adjustment, and grayscale conversion. These operations use preview and recoverable commit. Saturation, hue, white balance, sharpening, stylistic filters, and beautification are outside the approved scope so the Image menu remains focused on annotation preparation rather than general photo editing.

Image quality checking is analysis-only, with file-list findings and filtering as specified [below](#image-quality-checking). Duplicate-image discovery is outside the Image menu; [near-duplicate annotation boxes](annotation-interaction.md) are a separate Canvas concern.

Specialized repair currently includes red and yellow frame removal. New specialized repairs require representative real samples and explicit acceptance criteria before they enter the capability catalog. Manual region blur or mosaic, watermark removal, background removal, denoising, and super-resolution are not planned speculatively.

The Image menu presents Crop first, followed by a Rotate / Flip submenu containing every quick transform and Batch Geometry Transform… for previewed geometry work with an explicit target scope. Separators distinguish pixel correction through Adjust Image…, analysis through Check Image Quality…, specialized repair through its submenu containing Remove Red/Yellow Borders…, and committed recovery through Undo Last Image Processing….

## Target selection

Every mutating image-tool session begins with an explicit target set, defaulting to the current Canvas image. A batch-capable workspace separately offers “Selected images (N)” when multiple files are selected and “All images (N)” when the workspace contains multiple images. Both batch scopes require explicit choice; All includes images hidden by file-list filters, and opening a tool never infers a directory-wide batch. These rules also apply to rotation, flip, and resize; Crop is current-image-only. Analysis-only quality checking has its own all-images default.

Geometry and adjustment keep the target list beside the large preview. Border repair places Images and Detected Borders in adjacent sidebar tabs, with scope and detection controls above them. Results are prepared in the background, each image can be inspected, and any image can be excluded before commit. Images with no selected repair candidates are automatically excluded and retain their exact original bytes. Layout and compact copy follow the [global presentation contract](ui-presentation.md).

## Workspace and history

The pixel-tool workspace is modal and suspends annotation interaction while open. An unresolved drawing, vertex drag, edge drag, or other pending annotation gesture blocks entry; already committed but unsaved annotations are allowed and remain untouched. Crop instead uses a temporary Canvas mode that keeps annotations visible but non-interactive and resolves unsaved annotation changes before entry.

Multiple pixel-tool steps may be composed before one workspace commit. A tool-specific workspace may own transient history when its interaction requires it, but Adjust Image exposes its current values directly and has no temporary Undo/Redo controls. Geometry-changing Canvas modes keep their own transient adjustment history and commit separately. The main annotation workbench keeps its existing annotation-only Undo/Redo contract.

Settings return to safe defaults whenever the workspace opens. They are not persisted across invocations, workspaces, or launches.

## Geometry transforms

Image → Batch Geometry Transform… previews rotation, flip, and proportional resize under the target rules above and requires explicit Apply. Specific menu commands may enter it with the operation preselected. Geometry preparation preflights every image and its associated annotation resources before an atomic batch commit.

Rotation and flip additionally provide quick transforms for the current image. Rotate clockwise 90 degrees, rotate counter-clockwise 90 degrees, rotate 180 degrees, flip horizontally, and flip vertically skip the workspace and confirmation, then immediately transform the image and annotations and commit them atomically. Each invocation creates its own recoverable image-processing entry. Quick transforms are disabled during a pending annotation gesture, unresolved annotation conflict, or active crop session; selected files never become an implicit quick-transform target.

Quick transforms have no keyboard shortcuts and are invoked through the Image menu or top Rotate/Flip split commands. Committed but unsaved annotations use the existing Save, Discard, or Cancel flow before transformation; the tool never saves implicitly, and Cancel leaves the image unchanged.

## Resize

Resize performs proportional resampling only. Aspect ratio is locked, and the user may enter a target width, target height, or percentage; changing any one derives the others. An automatic interpolation policy chooses an appropriate resampler for reduction or enlargement. Enlargement is allowed only after an explicit warning that it adds no source detail. Forced stretching and Letterbox padding are excluded because they belong to training or export preprocessing rather than in-place annotation-source preparation.

## Pixel correction

Image → Adjust Image… opens one shared modal workspace for brightness, contrast, advanced Gamma, one-shot automatic adjustment, and grayscale conversion. Brightness, contrast, and Gamma use compact horizontal sliders with persistent numeric value badges and remain keyboard accessible. Auto Adjust analyzes a bounded, source-derived preview of the current image, ignores fully transparent pixels, and writes a robust luminance-based suggestion into all three sliders without changing the grayscale choice. It uses the 1st and 99th luminance percentiles plus the median, preserves color by applying one shared curve, avoids contrast and Gamma amplification for nearly flat content, and always recomputes from the source preview rather than the adjusted result. Reset restores all three sliders to their neutral values and turns grayscale conversion off without changing the target scope. For a selected-images or all-images scope, the visible current-image suggestion is the one parameter set applied to the entire target set. Controls remain directly refinable before one recoverable pixel-only commit. No correction receives an independent toolbar button.

## Canvas display adjustment

Display Adjustment changes only Canvas image presentation. Source-image bytes, annotation documents, dirty/save state, annotation Undo/Redo, and committed image-processing/recovery histories remain unchanged. Boxes, labels, handles, crop overlays, file-list presentation, and quality state retain their normal appearance and behavior. Image → Adjust Image… separately decodes the unadjusted source, starts from neutral defaults, and permanently processes pixels; returning to the workbench reapplies display values.

### Floating panel

A 36-pixel trigger stays 12 pixels from the Canvas viewport's lower-left corner while the image zooms and pans beneath it. It toggles a persistent 248-pixel panel above the button without changing the active tool or consuming layout width. Only the trigger closes the panel. View → Display Adjustment is non-checkable, opens it one-way, and has no global shortcut. Neither the rail nor the status strip contains this control.

The panel expands upward and rightward, stays within the viewport, and scrolls internally when height is constrained. Its theme-adaptive surface has a neutral one-pixel border, restrained rounding/shadow, compact slider rows, and no repeated title or close button. All Images and Current Image headings share a left origin and header baseline; each has an icon-only Reset drawn as one arc arrow without an inner glyph. Labels are Display Adjustment / 显示调节, All Images / 所有图像, and Current Image / 当前图像; reset tooltips and accessible names are Reset All / 重置所有图像 and Reset Current / 重置当前图像.

Every launch and annotation workspace starts with neutral values and a closed panel; values never persist beyond the workspace. Closing the panel retains its values and Canvas result. Without an image, the trigger stays visible but disabled, reports No image open / 未打开图像, and cannot open the panel or stage future values.

### Scope and reset

The All Images brightness/contrast sliders show -100 through +100, with zero neutral, and apply to the entire workspace including filtered-out images. A project-drawn chevron expands Current Image's override sliders. The disclosure remains open during navigation, follows the current image, and restores its remembered session values on revisit. Before an override exists, the sliders display inherited master values without creating an override; editing either creates an absolute pair that replaces, rather than adds to, the master values.

Changing either master slider clears all overrides. Reset All returns both master values to zero and clears all overrides; Reset Current clears only the current override and resumes inheritance. An active override gives its disclosure a restrained selected treatment and enables Reset Current; otherwise that reset is disabled. The interface uses neither Following All nor Individually Adjusted terminology.

Overrides follow application-owned rename/move, disappear on deletion, and clear for an image whose source pixels change through processing or external replacement. Master values are reapplied to replacement pixels, and other images retain their overrides.

Both contrast scopes use the same black-anchored algorithm as permanent adjustment: -100 maps to factor 0.1, zero to 1.0, and +100 to 3.0.

### One-shot restoration and status

A master-slider gesture or Reset All that clears overrides presents one non-modal inline notice with the cleared count and one-shot Restore. It restores the master pair and all overrides from before that gesture, outside annotation Undo/Redo. Coalesced pointer or keyboard changes retain the original pre-gesture snapshot. That snapshot survives navigation and expires on the next display-adjustment operation or workspace close.

The trigger's selected surface means the panel is open. A small amber mark independently indicates effective adjustment or pending Restore, with an explanatory tooltip; render failure takes priority with a red mark. Reopening exposes the corresponding inline Restore or Retry action, without a toast or status-bar entry.

### Rendering and navigation

Slider changes are coalesced into a bounded low-resolution preview away from the GUI thread. The Canvas keeps source dimensions as its logical coordinate space and stretches only the temporary raster, preserving geometry, zoom, pan, and pointer mapping. Preview and full-resolution work share one latest-only worker; new values supersede queued stale work instead of competing for memory bandwidth. Release schedules the latest full-resolution result for zoomed inspection. Controls are disabled only during an active Canvas pointer gesture and re-enable on release; Draw and Crop otherwise retain access without clearing geometry.

A render failure shows unadjusted source pixels for that image plus a localized inline failure, retaining values and other images' state for Retry or Reset. An older successful render must never appear to represent newer values.

Navigation prepares a coalesced display-sized destination before changing the current image. The prior image remains current under a visible loading state until ready, so an unadjusted destination never flashes. Rapid navigation rejects stale work; only the latest requested destination becomes current. Full-resolution rendering continues after the responsive Canvas transition.

## Image quality checking

The dialog starts with the standard policy summary and an explicit **Start Check** action. **Customize thresholds** expands one aligned column of fields, with pixel units and guidance for blur and brightness. Returning to the standard policy ignores staged custom values. The result panel offers a start action when empty, distinguishes all-passed counts and unreadable files, and retains a visible failure state with diagnostic detail. Empty-result refresh/clear controls are disabled. Inputs and the fixed footer remain reachable at supported display scales.

Image → Check Image Quality… explicitly offers the current image, selected images, or All images in the current annotation workspace; the all-images scope is the default. Checking runs in the background, is cancellable, and reports findings by problem type and severity without changing images or annotations.

Findings are cached under the application configuration directory and keyed by file path, content fingerprint, and the check policy that produced them. A changed file or changed check policy invalidates the affected cached result. The file list displays and filters those derived findings without conflating them with annotation review state, and no cache or sidecar is written into image or annotation directories.

One image may retain multiple findings. Unreadable or corrupt content is an error; low resolution, aspect-ratio anomalies, blur, excessive darkness, and overexposure are severity-ranked warnings. Findings never change the separate Unreviewed, Needs Review, or Verified annotation review state. An unreadable image cannot enter the normal Canvas, while warnings do not block annotation.

Every check starts with a visible Standard policy. Advanced controls may override its thresholds for that scan, and the exact effective policy is stored with the results; an override does not silently become the next scan's default. Named policies are not currently exposed.

The file list shows quality badges and supports finding and severity filters. An on-demand non-modal Image Quality panel summarizes counts, lists details, and navigates to affected images without permanently occupying the single-image annotation workbench.

The first quality engine is deterministic, explainable, and local; it neither downloads nor loads an AI model. Every finding reports the measured value, effective threshold, and reason. Readability comes from actual decoding, low resolution from image dimensions, aspect anomalies from both absolute extremes and workspace-distribution outliers, blur from Laplacian variance, and excessive darkness or exposure from mean luminance. The Standard policy exposes its thresholds in the check dialog instead of treating them as hidden product assumptions.

The Image menu and Image Quality panel can recheck the current image, selected images, or current workspace and can clear quality findings. A changed file or changed check policy immediately becomes Unchecked instead of displaying a stale finding. Clearing results removes only the application-owned cache and never changes image or annotation files.

## Geometry synchronization invariant

A geometry-changing image-processing commit or recovery is not complete when its file replacements alone succeed. Before LabelImg reports success or re-enables drawing, annotation editing, saving, Undo/Redo, or navigation, it synchronously projects the resulting or restored dimensions into the decoded current image and Canvas bounds, annotation shapes and label-list rows, the active in-memory annotation document and clean baseline, annotation-history snapshots or their replacement baseline, and every retained per-image workspace cache and resource fingerprint. The candidate-label vocabulary contains class names rather than geometry and is therefore outside this size synchronization.

Every one of those projections must describe the same image-annotation coordinate space. Canvas bounds and history retain the full decoded dimensions even when display-adjustment previews are downsampled; drawing after processing or recovery obeys the same snapshot invariant as drawing after load. For a non-current image, processing or recovery must rebase or discard any retained geometry-dependent in-memory state before that state can be reused. LabelImg must never expose an editable mixture of old and new dimensions or defer correction until a later save, reload, or navigation. If synchronous projection cannot be completed, the operation remains unsuccessful and must roll back or keep editing blocked while reporting the failure.

## Crop current image

Image → Crop… and the [Canvas rail](canvas-tool-rail.md#left-canvas-tool-rail) enter crop mode for the current image; `C` does the same only while the Canvas owns keyboard interaction. Crop owns the same cursor regardless of entry route, is unavailable without an image, and remains visibly checked while active. Pressing `C` again does nothing; `Esc` cancels and Canvas-focused `Enter` applies.

Crop mode suspends annotation editing and displays a dimmed outside region. Entering or leaving crop mode never changes the Canvas or viewport geometry. The user drags on the Canvas to create a crop region, then moves it from the interior or resizes it from any point along one of the four complete edges; the corner hit zones resize both axes and take priority over edge hit zones, which take priority over interior movement. The edge and corner hit zones retain a fixed screen-pixel tolerance at every zoom level. Dragging outside an existing region replaces it.

A floating tool-options panel is overlaid at the top center of the Canvas viewport without participating in application layout. It can be dragged anywhere within the viewport to avoid important image content, remains stationary until the crop session ends, and returns to the top center the next time crop mode starts. The panel exposes free, original, 1:1, 4:3, and 16:9 ratios; integer X, Y, width, and height fields; and explicit Apply Crop and Cancel actions. Before a crop region exists, X and Y are read-only live zero-based image coordinates for the pointer, retain the last valid in-image position after the pointer leaves, and width and height show zero and remain disabled. Once a region exists, all four fields switch to editable crop-region geometry. Enter in a numeric field accepts that value and returns focus to the Canvas without applying. Direction keys move the region by one image pixel and Shift plus a direction key moves it by ten.

These crop-panel fields are distinct from the [Canvas status-strip readouts](canvas-tool-rail.md#bottom-canvas-status), whose pointer coordinates become unavailable outside the image.

Free ratio is the default. A locked-ratio corner drag keeps the opposite corner fixed; an edge drag changes the perpendicular dimension around the region center. Width and height inputs update each other while locked. Switching ratios preserves the region center and fits the adjusted region within image bounds. A crop region is always an integer, in-bounds rectangle of at least 1 by 1 pixel. No region and a full-image no-op both disable Apply.

Annotations remain visible but cannot be edited in crop mode. The region previews their resulting geometry: contained boxes translate to the new origin, intersecting boxes clip to the new bounds whenever a positive-area intersection remains, and boxes outside the region disappear. There is no hidden visibility threshold. Applying a crop that clips or removes annotations first reports both counts and asks for confirmation. Crop-region creation and adjustment have their own transient Ctrl+Z and Ctrl+Y/Ctrl+Shift+Z history, which is discarded on cancel and never enters annotation history.

Before crop mode starts, unresolved annotation changes use Save, Discard, or Cancel. Apply atomically commits the resized image and transformed annotations as a new clean baseline under the [geometry synchronization invariant](#geometry-synchronization-invariant); ordinary annotation Undo cannot return to pre-crop coordinates. [Image-processing recovery](#recovery) restores image and annotations together as the replacement baseline, refusing a changed recovery unit while preserving unrelated CreateML records.

Crop preserves the zoom factor, translates the viewport by the crop origin, and clamps it to the new image bounds. Selection survives for retained annotation boxes and drops removed boxes. Leaving the image, switching tools, or closing while a crop region has been created offers Apply Crop, Discard Crop, or Cancel; a session with no region exits silently. Crop and pixel-only image tools commit as separate ordered operations rather than composing in one uncommitted session.

## Remove red and yellow frames

The tool treats saturated red and yellow pixels as candidates using the [detector's OpenCV HSV ranges](../../src/labelimg/image_tools/domain/colored_frame_removal.py): red `(0, 100, 80)`–`(10, 255, 255)` or `(160, 100, 80)`–`(180, 255, 255)`; yellow `(20, 120, 120)`–`(35, 255, 255)`. Color alone is insufficient: a candidate must also resemble a rectangular outline under the conservative, standard, or loose geometry policy. Solid colored regions and ordinary red or yellow objects are not frame overlays.

The default controls select red and yellow, use standard detection strength, and allow Original, Result, and Repair Mask preview modes. Original and Result identify each candidate with a fixed 22-pixel numbered ring anchored just inside its top-left corner; Repair Mask remains a pure pixel preview. The number matches the candidate list. Included candidates use a theme-accent ring and number, while excluded candidates use a neutral ring and number. Candidate markers never use red or yellow, so they cannot be mistaken for image content.

The numbered rings are non-pixel UI overlays: they are painted after the preview image and never enter the preview base pixmap, committed image, or annotations. A candidate can be toggled only through its ring or its candidate-list row; the rest of its detected rectangle is not an invisible click target. Hovering a ring shows its number, detected color, current inclusion state, and click action without changing selection. Badges remain 22 screen pixels across while zooming or resizing, stay inside image edges, and move deterministically when their preferred positions collide. Excluding a candidate retains its number for the current analysis; changing detection options may re-run analysis and renumber candidates in top-to-bottom, left-to-right order.

Each detected frame is separately selectable so a false positive can be excluded without excluding the whole image. The tool does not provide a brush, freehand mask, or manual missed-frame creation.

Repair uses Telea inpainting with a default radius of 3. Advanced controls expose the inpaint radius, bounded halo dilation, and whole-image near-grayscale normalization. Halo dilation defaults to zero. Whole-image grayscale normalization is explicit and defaults off; otherwise only the frame repair region may change color.

## Supported files and metadata

Supported input is 8-bit JPEG, PNG, or BMP, including RGB, grayscale, and applicable alpha-bearing content. Unsupported formats and bit depths are reported before commit and remain unchanged.

Pixel-only output retains the source path, filename, format, pixel dimensions, orientation behavior, alpha channel where applicable, and valid EXIF, ICC, and DPI metadata. Geometry-changing output retains the same compatible identity and metadata while replacing pixel dimensions with the explicit tool result. JPEG encoding reuses the source quantization and subsampling characteristics when available. An image that has no selected repair region is never re-encoded.

## Commit

Apply in the modal pixel-tool workspace closes it after success and refreshes the current Canvas image while preserving annotation content, selection, zoom, and pan. Geometry-changing Canvas tools instead apply their documented annotation transformation and geometry synchronization contract. The complete selected target set is prepared and validated before files change. Preparation is cancellable and leaves no user files behind. The short commit phase is not cancellable.

Commit stages every encoded result beside its source, preflights recoverable system-trash support, rechecks source fingerprints, moves every original to recoverable trash, and atomically installs every result. Any failure rolls the complete batch back. A system that cannot guarantee an actionable recovery identity cannot commit an in-place image operation.

## Recovery

Committed image processing does not enter annotation Undo or a tool's transient adjustment history. Image → Undo Last Image Processing… opens the latest committed operation. A single-image operation uses a confirmation; a multi-image batch lists every still-recoverable image and defaults to selecting all. A geometry-changing operation restores each image and its annotations as an indivisible recovery unit.

The user may restore an explicit subset. That selected subset restores atomically after verifying that each dedicated processed file still matches its committed fingerprint. For a shared CreateML file, the affected image record must still match the committed result, while unrelated records may have changed and are preserved. Unselected images keep their processed files and recovery eligibility. Earlier entries remain available through File → Recent File Operations….

One-click recovery is scoped to the current image workspace and clears when the workspace changes or the application exits. Originals remain in the system trash for manual recovery afterward. Image-processing recovery never overwrites an externally changed processed file.

## Concurrency and failure reporting

Specialized-repair preview work runs away from the GUI thread and reports per-image queued, processing, ready, no-frame, unsupported, failed, or excluded status. Closing or canceling the workspace cancels pending preparation and removes temporary results. Commit begins only when every included image is ready.

Interactive Image-menu adjustment reuses the workbench's already decoded
current `QImage` when available and derives an adaptive preview budget from the
actual preview widget and device-pixel ratio, bounded between 250,000 and 1.5
million pixels. Disk preview decoding remains the fallback for non-current
targets. Rapid control changes are coalesced before rendering and never run
metadata-preserving full-resolution encoding. The explicit Apply step still
reloads and processes every source at full resolution, then follows the normal
atomic replacement contract; the current target's prepared output is retained
through commit and projected directly back to the Canvas without decoding the
new file again. Quality metrics use at most 2 million decoded pixels while
retaining the full source dimensions for resolution and aspect checks.
Specialized-repair preparation remains full-resolution for candidate accuracy,
but runs on a single owned background queue so large images cannot multiply
memory pressure.

Normal image navigation uses a source-token-validated decoded-image LRU capped
at 256 MiB. Two background workers prefetch the adjacent visible images after a
successful load; a cache entry is ignored automatically when file size or
nanosecond modification time changes. Shutdown cancels queued prefetches and
releases the cache. Brightness, contrast, and Gamma share cached 8-bit lookup
tables, and the common RGBA path adjusts all color channels while preserving
alpha in one OpenCV pass.

Cold navigation to images above four million pixels decodes away from the GUI
thread. The previous image remains current until the latest requested destination
is ready; successive Previous/Next commands advance from the pending destination.
There is one active demand decode and one replaceable pending destination, so key
repeat cannot build an unbounded decode queue. Direct loads, workspace resets,
image-tool commands, and starting a new annotation gesture cancel pending
navigation. Completion rechecks the source token, workspace membership, and
annotation navigation guard before publishing pixels. Failure retains the prior
image and counter. Demand loading reuses an in-flight adjacent prefetch. Images
too large to share the LRU with another neighbor are not speculatively decoded;
inserting an uncacheable image does not evict useful cached neighbors.

Canvas retains a separate image raster for the visible viewport, capped at
16 million device pixels. It is rebuilt only when source pixels, logical image
dimensions, transform, viewport, DPR, or render hints change. Annotation geometry,
reverse-screen drawing feedback, and magnifier sampling continue to use original
image coordinates and the current display pixmap. Pointer motion, box dragging,
and repeated keyboard nudges queue repaint requests so Qt can coalesce a burst.
The cache is cleared when pixels are replaced or the image session resets.

Committed 90/180-degree rotations, flips, and crops use the codec's native
Pillow geometry operations so pixels do not make an intermediate full-image
NumPy round trip. Proportional resize keeps the faster OpenCV resampler.
Multi-image geometry and adjustment preparation may run concurrently, but the
worker count is capped by both CPU count and a 768 MiB estimated live-pixel
budget; atomic commit still begins only after every output is ready.

The GUI snapshots annotation and workspace state before background pixel
preparation. A modal progress dialog keeps event processing alive and permits
cancellation without writing user files. Cancellation discards the plan and
prevents pending targets from starting; an already running codec may finish in
the background. One owned preparation queue serializes operations, including
cancelled work still finishing, so repeated cancellation cannot multiply large
pixel buffers. Image encoding, annotation serialization, and decoding the
current geometry result happen during preparation. The ready decoded result is
reused during the synchronous GUI projection after atomic commit. Worker-side
byte decoding uses `QImageReader.read()` through a `QBuffer`: the PyQt static
`QImage.fromData()` binding otherwise retains the Python GIL during decoding.
Only metadata is retained for non-current source documents, avoiding a full
decoded image per batch member. Current-image geometry and adjustment dialogs
both reuse bounded preview pixels from the workbench image; full-resolution
encoding is reserved for Apply.

Failures identify the affected image and phase under the [bilingual interface contract](bilingual-interface.md#translation-boundary).

Every Image-menu command and every signal-driven preview callback is an
exception boundary. Decode, codec, and allocation failures become localized
failure states instead of escaping into Qt's event loop; a workspace whose
preview failed disables Apply and leaves source files unchanged.

## Validation

Validation must exercise the behavioral contracts above through pixel preparation/commit/recovery, crop geometry and joint annotation projection in all three formats, and display-adjustment state/rendering. Failure coverage includes cancellation, rollback, external changes, stale work, allocation/codec failures, and preservation of the active Canvas and annotation state. No-op repair must retain exact source bytes; color/metadata checks include negative objects, alpha, and explicit grayscale normalization.

With the source environment described in the root README, run:

```powershell
$env:PYTHONPATH = "src"
python tools/benchmark_interaction.py --assert-budget --output .test-state/latency/result.json
```

This runs a disposable 10000 × 7000 image through
crosshair motion, drawing with 500 boxes, cold/warm direct loads, rapid alternating
navigation, preview opening, and geometry preparation. It reports input-handler
latency, paint latency, final destination correctness, and GUI heartbeat gaps
separately from total decode/processing time. The frame/request budget assertions
are a local diagnostic, while deterministic regressions verify work coalescing,
cache bounds, pixel equivalence, stale results, cancellation, and thread ownership.
Offscreen timings are comparative evidence; they do not certify native desktop
frame pacing, slow network storage, all codecs, or all image sizes.

The [frame-removal tests](../../tests/image_tools/test_colored_frame_removal.py) include synthetic fixtures and optional local red-frame samples selected by `LABELIMG_RED_FRAME_SAMPLES` (with a historical local-directory fallback). Those samples are not repository fixtures: report real-sample checks and skips separately, and do not generalize synthetic yellow, mixed-color, or negative-object evidence into real-data acceptance.
