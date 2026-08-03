# Copy Windows Recycle Bin identities as absolute PIDLs

The Windows trash adapter will use an item-specific `IFileOperationProgressSink` and immediately copy the absolute PIDL bytes from `PostDeleteItem`'s `psiNewlyCreated` value with `SHGetIDListFromObject`. Availability checks and restore reconstruct a fresh `IShellItem` with `SHCreateItemFromIDList`; the callback-owned COM pointer is never retained beyond the callback.

Before any user file is changed, the adapter recycles and restores a same-directory probe. A missing `psiNewlyCreated`, invalid PIDL, failed availability check, or failed probe restore blocks the real operation. This deliberately means a volume without a restorable Recycle Bin identity cannot use LabelImg deletion or clearing; permanent deletion and filename/timestamp matching are not fallbacks.

Retaining the raw callback pointer is rejected because its lifetime is not owned by the application and produced an access violation during delayed restore. Searching the Recycle Bin by name or deletion time is rejected because concurrent deletions make that identity ambiguous.
