---
status: accepted
---

# Open large directories progressively with session-only indexes

Large image and annotation directories will become usable before every derived file state is ready. A directory switch becomes authoritative only when the current image and its annotation document can be replaced atomically; remaining annotation states are incorporated in the background under a loading generation, and results from canceled or superseded generations are discarded. The complete index exists only in memory for the current application session and is never written to disk or reused across sessions. This preserves editing and save-target consistency while avoiding both a blocking full scan and the invalidation complexity of a persistent index.

Name-based navigation is available at directory ready state, while annotation-, review-, alert-, and quality-dependent controls remain unavailable until their required data is complete. Rows do not reorder as incremental states arrive. Image-quality content validation remains an explicit operation rather than part of directory indexing. The implementation must retain one authoritative owner per mutable concept, keep discovery and annotation indexing free of Qt, and confine background scheduling, cancellation, and model projection to the UI layer.
