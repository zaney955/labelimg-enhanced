# Bilingual Interface Design

## Outcome

LabelImg exposes one application-language preference with exactly two values: Simplified Chinese and English. The preference applies to all application-authored interface text, takes effect immediately in the current window, and persists across launches.

On first launch, every `zh-*` system locale maps to Simplified Chinese. Every other locale maps to English. The language menu uses the self-identifying names “简体中文” and “English” in both interface languages.

## Translation boundary

Translated text includes commands, menus, toolbars, panels, filters, sorting, status messages, tooltips, validation, confirmations, recovery, conflict resolution, annotation-history feedback, and application-owned buttons.

The following values are deliberately not translated:

- user-authored annotation labels;
- file names and paths;
- Pascal VOC, YOLO, and CreateML format names;
- verbatim operating-system diagnostics.

When an operating-system diagnostic is shown, LabelImg supplies a localized title or explanation around the unchanged diagnostic.

## Catalog

`src/labelimg/translations.py` is the single source of application messages. English and Simplified Chinese catalogs use the same stable message IDs. English is the semantic fallback; an unknown message ID is a programming error rather than text to expose to the user.

The historic `StringBundle` API remains as a compatibility facade, but the Qt resource bundle no longer carries partial Japanese, Traditional Chinese, or legacy property catalogs. This prevents the application from presenting an apparently supported but incomplete language.

## Runtime behavior

`src/labelimg/i18n.py` owns locale normalization, the selected language, catalog lookup, and the language-change signal. The main window loads the saved preference before constructing visible controls. Choosing View → Language updates persistent settings immediately and retranslates long-lived widgets, actions, menus, panels, summaries, and tooltips without recreating the annotation workspace.

Transient context menus and dialogs translate their text when opened. Application-owned dialog and message-box buttons receive explicit bilingual labels because the supported PyQt bundle lacks `qtbase_zh_CN`; standard buttons therefore use the same language without relying on platform translation availability. Native operating-system dialogs remain operating-system text by design. User data and active annotation state are untouched by a language switch.

Internal annotation-history descriptions remain stable English identifiers inside history state. They are translated only when projected into Undo, Redo, and pending-operation text, so switching languages never mutates or invalidates history.

## Validation

The localization tests enforce:

- identical English and Simplified Chinese message-ID sets;
- matching formatting fields across translations;
- `zh-*` and unsupported-locale mapping rules;
- safe English/Chinese lookup and unknown-ID failure;
- immediate main-window retranslation and preference persistence;
- Simplified Chinese and English Qt standard-button labels;
- existence of every statically referenced message ID;
- absence of hard-coded application-language text in UI construction and presentation calls.

The normal per-file Qt test runner continues to validate all annotation, selection, history, file-operation, recovery, and persistence behavior under the localized interface.
