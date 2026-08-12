# Top-level menu information architecture

LabelImg Enhanced uses one stable six-menu order:

1. File
2. Edit
3. Image
4. View
5. Settings
6. Help

File owns workspace entry, annotation storage, the current image file, file-operation recovery, and application exit. Annotation copy, paste, duplication, and previous-image copy belong only to Edit. Reset All Settings belongs only to Settings.

Edit owns current-image annotation creation, Undo and Redo, label and box operations, previous-image annotation copy, and default drawing constraints.

Image is the complete catalog for annotation-preparation image work. Its separators distinguish geometry preparation, pixel correction, analysis-only quality checks, specialized repair, and committed image-processing recovery.

View owns visible presentation and Canvas scale: box-label rendering, the annotation panel, box visibility, zoom, and fit commands. It does not own application preferences.

Settings owns Language, Autosave, Single Class Mode, and Reset All Settings. Save As retains `Ctrl+Shift+S`; Single Class Mode has no shortcut so the sequence is unambiguous.

Help presents Tutorial and Keyboard Shortcuts first, followed by About LabelImg Enhanced.
