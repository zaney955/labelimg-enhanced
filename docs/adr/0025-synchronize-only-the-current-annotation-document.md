# Synchronize only the current annotation document

LabelImg will continuously watch only the active annotation storage resources for the image currently displayed on the Canvas, automatically rebasing a clean document after a stable valid external change and requiring explicit conflict resolution when local edits are dirty. Inactive images will instead read their latest stored documents when opened. This replaces the earlier no-watcher rule because users need external edits to appear while an image remains open, while deliberately avoiding whole-workspace monitoring, background history replacement, and the scaling and ambiguity costs of continuously reconciling every annotation file.

