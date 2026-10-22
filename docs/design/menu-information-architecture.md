# Top-level menu information architecture

This document owns menu order and command placement; [Canvas command surfaces](canvas-tool-rail.md) specify the visible workbench controls. LabelImg Enhanced uses one stable seven-menu order:

1. File
2. Edit
3. Image
4. View
5. Tools
6. Settings
7. Help

File owns workspace entry, annotation storage, the current image file, file-operation recovery, and application exit. Annotation copy, paste, duplication, and previous-image copy belong only to Edit. Reset All Settings belongs only to Settings.

Edit owns current-image annotation creation, Undo and Redo, label and box operations, previous-image annotation copy, and default drawing constraints. A final separate group contains **Replace Label Names…**, an explicitly scoped cross-image content operation with a preview. It has no Canvas or annotation-group context-menu entry because those surfaces target the current image's boxes.

Image is the complete catalog for annotation-preparation image work. Its separators distinguish geometry preparation, pixel correction, analysis-only quality checks, specialized repair, and committed image-processing recovery; [Image Tools](image-tools.md#approved-capability-boundary) specifies the commands and processing contracts.

View owns visible presentation and Canvas scale: box-label rendering, the annotation panel, box visibility, independent drawing-center suppression and selected-target clipping, the crosshair magnifier, annotation display settings, zoom, and fit commands. The two hiding controls follow Hide All / Show All, are initially off, have no shortcut, and remember their individual choices (migrating the old combined setting). Crosshair Magnifier shares one action with its Canvas-status-strip button and Canvas-scoped `M` shortcut. Annotation Display Settings provides live preview of line width and label text size with cancel rollback. These presentation choices remain in View even when persisted between launches.

Settings owns [Appearance…](themes.md), Language, Label Color Algorithm, Autosave, Single Class Mode, Automatically Check for Updates, and Reset All Settings. [Label Color Algorithm](session-label-color-palette.md) selects the default fixed full-name mapping or session maximum-separation allocation without storing category-color mappings. Save As retains `Ctrl+Shift+S`; Single Class Mode and update checking have no shortcuts so the sequence is unambiguous.

Tools owns independent checks, organization, and maintenance of image/annotation datasets. [Clean Annotation Files…](annotation-cleanup.md) and [Annotation Statistics…](annotation-statistics.md) appear directly in the menu, with no toolbar buttons or shortcuts. Add future utilities directly and group related commands with separators as the catalog grows; introduce submenus only when the actual command count needs them. Existing file, annotation-editing, and image-processing commands retain their established locations. Annotation Directory remains a directory-selection/status surface.

Help presents Tutorial and the [bilingual Keyboard Shortcuts catalog](bilingual-interface.md#keyboard-shortcut-catalog) first, then Check for Updates, followed by About LabelImg Enhanced. [Update checking](application-updates.md) belongs in Help; only its automatic-check preference belongs in Settings.
