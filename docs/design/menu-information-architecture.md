# Top-level menu information architecture

This document owns menu order and command placement; [Canvas command surfaces](canvas-tool-rail.md) specify the visible workbench controls. LabelImg Enhanced uses one stable six-menu order:

1. File
2. Edit
3. Image
4. View
5. Settings
6. Help

File owns workspace entry, annotation storage, the current image file, file-operation recovery, and application exit. Annotation copy, paste, duplication, and previous-image copy belong only to Edit. Reset All Settings belongs only to Settings.

Edit owns current-image annotation creation, Undo and Redo, label and box operations, previous-image annotation copy, and default drawing constraints.

Image is the complete catalog for annotation-preparation image work. Its separators distinguish geometry preparation, pixel correction, analysis-only quality checks, specialized repair, and committed image-processing recovery; [Image Tools](image-tools.md#approved-capability-boundary) specifies the commands and processing contracts.

View owns visible presentation and Canvas scale: box-label rendering, the annotation panel, box visibility, independent drawing-center suppression and selected-target clipping, the crosshair magnifier, annotation display settings, zoom, and fit commands. The two hiding controls follow Hide All / Show All, are initially off, have no shortcut, and remember their individual choices (migrating the old combined setting). Crosshair Magnifier shares one action with its Canvas-status-strip button and Canvas-scoped `M` shortcut. Annotation Display Settings provides live preview of line width and label text size with cancel rollback. These presentation choices remain in View even when persisted between launches.

Settings owns Language, Label Color Algorithm, Autosave, Single Class Mode, Automatically Check for Updates, and Reset All Settings. [Label Color Algorithm](session-label-color-palette.md) selects the default fixed full-name mapping or session maximum-separation allocation without storing category-color mappings. Save As retains `Ctrl+Shift+S`; Single Class Mode and update checking have no shortcuts so the sequence is unambiguous.

Help presents Tutorial and the [bilingual Keyboard Shortcuts catalog](bilingual-interface.md#keyboard-shortcut-catalog) first, then Check for Updates, followed by About LabelImg Enhanced. [Update checking](application-updates.md) belongs in Help; only its automatic-check preference belongs in Settings.
