---
status: accepted
---

# Use single state owners and explicit feature coordination

Every mutable application concept will have one authoritative owner: `WorkbenchSession` owns current-image session transitions, annotation services own documents and revision state, Canvas owns transient geometry and selection, the files feature owns its view state and batch selection, image-processing services own processing plans and recovery records, and platform settings own persisted window preferences. Qt actions and widgets are projections rather than competing state stores. User-interface notifications use Qt signals, use cases use direct calls through feature public interfaces and return structured results, and cross-feature transactions use explicit coordinators; a global event bus and widget-to-widget or `MainWindow` lookup are rejected because they would hide ordering and recovery behavior. `MainWindow` will be judged by its remaining shell responsibilities, with roughly 1,000–1,500 lines and a roughly 150-line constructor used only as soft review signals. Generic `common`, `core`, and expanding `utils` modules are also rejected: code belongs to the feature that gives it meaning, platform adapters belong to `platform`, and only genuinely reusable Qt primitives belong to the top-level `ui` package.
