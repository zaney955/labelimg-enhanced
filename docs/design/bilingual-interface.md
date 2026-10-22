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

[The message catalogs](../../src/labelimg/localization/catalogs.py) are the single source of application messages. Both languages use the same stable message IDs and formatting fields. English is the semantic fallback; an unknown message ID is a programming error rather than text to expose to the user.

Partial Japanese, Traditional Chinese, and legacy property catalogs are not supported. All statically referenced message IDs must exist, and UI construction and presentation must not hard-code application-language text.

## Runtime behavior

[The localization runtime](../../src/labelimg/localization/runtime.py) owns locale normalization, the selected language, lookup, and the language-change signal. The main window loads the saved preference before constructing visible controls. Choosing Settings → Language persists the choice and retranslates long-lived widgets, actions, menus, panels, summaries, and tooltips without recreating the annotation workspace.

Transient context menus and dialogs translate their text when opened. Application-owned dialog and message-box buttons receive explicit bilingual labels because the supported PyQt bundle lacks `qtbase_zh_CN`; standard buttons therefore use the same language without relying on platform translation availability. Native operating-system dialogs remain operating-system text by design. User data and active annotation state are untouched by a language switch.

Internal annotation-history descriptions remain stable English identifiers inside history state. They are translated only when projected into Undo, Redo, and pending-operation text, so switching languages never mutates or invalidates history.

The application-owned Qt translator also covers the built-in color picker's controls and standard button contexts. It follows the current language, preserves the selected RGBA value, and returns no translation for unknown Qt messages. Shared sections, compact summaries and transient dialogs follow the [global presentation contract](ui-presentation.md).

## Keyboard shortcut catalog

Help → Keyboard Shortcuts provides the complete bilingual catalog of keyboard commands and context-specific interactions, grouped by where they apply. Each entry includes its current binding and a concise usage explanation; Canvas and annotation-list mouse gestures are included where they explain the same interaction. Menu ownership follows [the menu contract](menu-information-architecture.md).

## Validation

Localization validation checks catalog/format-field parity, static references, fallback and locale mapping, live retranslation, persistence, and explicit Qt button labels. Existing behavior suites exercise annotation, file, history, recovery, and persistence workflows under the localized interface; [the architecture guide](modular-architecture-refactor.md) owns repository validation instructions.
