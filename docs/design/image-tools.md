# Image Tools Workspace

## Outcome

LabelImg Enhanced provides a built-in Image menu and one shared modal image-tools workspace. The first tool removes red and yellow rectangular frame overlays; later crop, brightness, and other pixel operations join the same preview, history, commit, and recovery model without moving image editing into the annotation Canvas.

## Target selection

Every session begins with an explicit target set. The current Canvas image is always the safe default. When the file list contains multiple selected images, the workspace offers a separate “Selected images (N)” scope that the user must choose explicitly; opening a tool never infers the complete directory as a batch.

The target list remains visible in the workspace. Results are prepared in the background, each image can be inspected, and any image can be excluded before commit. Images with no selected repair candidates are automatically excluded and retain their exact original bytes.

## Workspace and history

The workspace is modal and suspends annotation interaction while open. An unresolved drawing, vertex drag, edge drag, or other pending annotation gesture blocks entry; already committed but unsaved annotations are allowed and remain untouched.

Multiple image-tool steps may be composed before commit. The workspace owns a transient Undo/Redo sequence: Ctrl+Z and Ctrl+Y operate on image-tool steps only while the workspace is active. The main annotation workbench keeps its existing annotation-only Undo/Redo contract.

Settings return to safe defaults whenever the workspace opens. They are not persisted across invocations, workspaces, or launches.

## Remove red and yellow frames

The tool treats saturated red and yellow pixels as candidates, using the reference HSV ranges from `remove_red_yellow_boxes.py`, but color alone is insufficient. A candidate must also resemble a rectangular outline under the selected conservative, standard, or loose geometry policy. Solid colored regions and ordinary red or yellow objects are not frame overlays.

The default controls select red and yellow, use standard detection strength, and allow Original, Result, and Repair Mask preview modes. Each detected frame is separately selectable so a false positive can be excluded without excluding the whole image. The first release does not include a brush, freehand mask, or manual missed-frame creation.

Repair uses Telea inpainting with a default radius of 3. Advanced controls expose the inpaint radius, bounded halo dilation, and whole-image near-grayscale normalization. Halo dilation defaults to zero. Whole-image grayscale normalization is explicit and defaults off; otherwise only the frame repair region may change color.

## Supported files and metadata

The first release accepts 8-bit JPEG, PNG, and BMP images. Unsupported formats and bit depths are reported before any commit and remain unchanged.

The output retains the source path, filename, format, pixel dimensions, orientation behavior, alpha channel where applicable, and valid EXIF, ICC, and DPI metadata. JPEG encoding reuses the source quantization and subsampling characteristics when available. An image that has no selected repair region is never re-encoded.

## Commit

Apply closes the workspace after success and refreshes the current Canvas image while preserving annotation content, selection, zoom, and pan. The complete selected target set is prepared and validated before files change. Preparation is cancellable and leaves no user files behind. The short commit phase is not cancellable.

Commit stages every encoded result beside its source, preflights recoverable system-trash support, rechecks source fingerprints, moves every original to recoverable trash, and atomically installs every result. Any failure rolls the complete batch back. A system that cannot guarantee an actionable recovery identity cannot commit an in-place image operation.

## Recovery

Committed image processing does not enter annotation Undo or the workspace's transient image-step history. Image → Undo Last Image Processing… opens the latest committed batch. A single-image batch uses a confirmation; a multi-image batch lists every still-recoverable image and defaults to selecting all.

The user may restore an explicit subset. That selected subset restores atomically after verifying that every processed file still matches its committed fingerprint and every corresponding original remains recoverable. Unselected images keep their processed files and recovery eligibility. Earlier entries remain available through File → Recent File Operations….

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

Automated validation covers red, yellow, mixed, no-frame, solid-color negative, per-candidate exclusion, grayscale normalization opt-in, alpha preservation, metadata retention, exact no-op bytes, format rejection, transient Undo/Redo, cancellable preparation, atomic commit rollback, selectable atomic recovery, external-change conflicts, bilingual UI, and preservation of Canvas annotation/view state.

The three JPEG files under `C:\Users\GW-LIYU\Downloads\red_box` are the initial real-data acceptance set for red-frame detection and repair. Yellow, mixed-color, and negative-object evidence is synthetic until representative real files are supplied; validation reports must preserve that distinction.
