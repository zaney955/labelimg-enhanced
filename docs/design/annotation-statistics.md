# Annotation statistics

**Tools → Annotation Statistics…** opens read-only category statistics for all images in the current workspace, including images hidden by search or filters. A standalone image is also supported. The command has no shortcut or toolbar button and does not interrupt an unfinished drawing/edit transaction.

The dialog starts a fresh scan and provides:

- total distinct used categories and annotation-box count;
- horizontal bars ordered by box count, switchable to the number of distinct images containing each category;
- category filtering that affects both chart and details without changing the workspace totals or share denominator;
- a numeric-sortable table of category, box count, distinct-image count, and share of all counted boxes;
- separate totals for annotated images, valid empty annotations, images without annotations, skipped images, and images with completed unsaved edits;
- a skipped-image table identifying paths and failures or unresolved document choices, plus a manual refresh command.

Only the active annotation document for each image contributes. An unopened image with one document uses that document; multiple mapped/flat locations or formats without an explicit choice are reported as skipped, preventing duplicate counts. An explicitly bound Save As target remains usable. Missing annotations and valid negative-sample documents are different states. Unused names from `classes.txt`, YAML, or default category lists are excluded.

Pascal VOC counts object elements. YOLO counts valid detection rows through the existing dataset-boundary/class-ID resolver and its mapping approvals, excluding review/comment lines. Shared CreateML files count only the matching image record, using the same reference and relative-path rules as workspace loading. A category appears once per image in image counts, even when that image has many boxes of that category.

Completed unsaved history snapshots replace that image's stored document counts, including unsaved removal of all boxes. Clean documents are read from disk. The scan decodes no image pixels and never saves documents, changes history, selects a document implicitly, or edits a class configuration. Autosave is paused while the modal report is open and resumes normally afterward.

The workspace annotation index is built independently of background-index readiness. Counting and index construction support cancellation; canceling or failing a refresh clears previous results rather than showing a partial result as complete. Resource/configuration fingerprints detect changes during the scan and require refresh. Per-image malformed documents and unresolved choices are listed explicitly; directory read failures abort the refresh.

The native Qt chart needs no additional plotting package. All categories remain available through scrolling, long names are elided with full-name hover text, integer count ticks preserve the units, and the details table and chart accessibility description expose the same values. Application text follows live Simplified Chinese/English changes; category names and paths remain verbatim.
