# LabelImg Enhanced modular architecture refactor

Status: accepted design; implementation requires the final shared-understanding confirmation.

## Outcome

LabelImg Enhanced 2.0 will be a feature-first modular monolith. The refactor changes package ownership, import paths, state ownership, and composition, but it does not change observable application behavior.

The application remains one Python distribution, one process, one main window, and one `labelImg` command. This is not a services split, plugin framework, UI redesign, or feature rewrite.

## Behavior invariants

The following are hard compatibility boundaries:

- visible UI, interaction sequences, shortcuts, menu semantics, and bilingual behavior;
- Pascal VOC, YOLO, and CreateML interpretation and persistence;
- annotation history, dirty-state, external-conflict, review, recovery, and partial-success semantics;
- settings keys and existing user settings;
- `labelImg` command-line behavior and `python -m labelimg`;
- supported Windows and Linux behavior;
- current test-observable behavior unless a test only asserts a removed internal import path.

Historical Python module paths are deliberately not compatibility boundaries. There will be no `labelimg.app`, forwarding modules, deprecated aliases, or dual import paths after the migration.

## Current baseline

At commit `e149661`:

- the repository already uses a correct `src/`, `tests/`, `tools/`, and `docs/` layout;
- `src/labelimg` contains 58 Python files: 40 at the package root and 18 in `image_tools`;
- `tests` contains 54 flat test files;
- `app.py` contains 6,541 physical lines;
- `MainWindow` contains 225 methods and accessors;
- the constructor spans approximately 1,081 lines;
- 16 test files import `MainWindow` directly;
- domain policies for annotation history, persistence, review, workspace state, storage, file recovery, and image processing already have useful module seams;
- the remaining central risk is orchestration and presentation state accumulated in `MainWindow`, not an absence of all modular design.

## Target source tree

The exact leaf filenames may be adjusted during implementation only when an inspected class boundary proves the proposed split incorrect. Feature ownership and dependency direction may not drift without revisiting the accepted ADRs.

```text
src/labelimg/
  __init__.py
  __main__.py
  data/

  workbench/
    __init__.py
    bootstrap.py
    main_window.py
    commands.py
    session.py
    navigation.py
    lifecycle.py
    recovery_ui.py

  annotations/
    __init__.py
    domain/
      __init__.py
      model.py
      history.py
    application/
      __init__.py
      editing.py
      workspace.py
      persistence.py
      review.py
      session.py
    infrastructure/
      __init__.py
      storage.py
      formats/
        __init__.py
        pascal_voc.py
        yolo.py
        create_ml.py
        create_ml_collection.py
    ui/
      __init__.py
      controller.py
      candidate_label_dialog.py
      label_group_list.py
      label_list.py

  files/
    __init__.py
    model.py
    application/
      __init__.py
      operations.py
      transaction.py
      recovery.py
    infrastructure/
      __init__.py
      filesystem.py
    ui/
      __init__.py
      controller.py
      list_widget.py
      filter_panel.py
      rename_dialog.py

  canvas/
    __init__.py
    widget.py
    shape.py
    selection.py
    interaction.py
    annotation_adapter.py
    geometry.py

  image_tools/
    __init__.py
    domain/
      __init__.py
      crop_geometry.py
      quality.py
      colored_frame_removal.py
    application/
      __init__.py
      session.py
      adjustment.py
      crop.py
      crop_annotations.py
      geometry_transform.py
      quality_scan.py
      colored_frame_processor.py
    infrastructure/
      __init__.py
      image_codec.py
      recoverable_replacement.py
    ui/
      __init__.py
      controller.py
      adjustment_dialog.py
      crop_overlay.py
      geometry_dialog.py
      quality_panel.py
      colored_frame_dialog.py
      recovery_dialog.py

  localization/
    __init__.py
    runtime.py
    catalogs.py

  platform/
    __init__.py
    settings.py
    settings_keys.py
    trash.py

  ui/
    __init__.py
    actions.py
    color_dialog.py
    icons.py
    tool_bar.py
    generated_resources.py
```

No `common`, `core`, `helpers`, or general-purpose `utils` package will be created.

## Feature ownership

| Feature | Owns | Does not own |
| --- | --- | --- |
| `workbench` | process bootstrap, top-level window, current-image session transitions, cross-feature wiring, navigation and close lifecycle | annotation policy, filesystem transaction mechanics, Canvas interaction, image algorithms |
| `annotations` | Qt-free annotation model, document formats, revision history, workspace identity, saving, review, candidate labels, annotation-specific UI | current file-list selection, Canvas `Shape`, operating-system trash |
| `files` | file collection operations, annotation-aware rename/delete/clear, file recovery records, file-list state and UI | annotation document semantics, image-processing algorithms |
| `canvas` | interactive `Shape`, transient geometry, selection, hover, hit testing, viewport interaction, annotation projection adapter | saved annotation identity, file transactions |
| `image_tools` | image transformations, crop, adjustment, quality analysis, recoverable replacement plans and their UI | top-level navigation, annotation storage policy |
| `localization` | active language, translation lookup and catalogs | feature policy or settings persistence |
| `platform` | settings persistence and OS-specific adapters | application decisions and dialogs |
| `ui` | genuinely cross-feature Qt primitives and generated resources | feature-specific widgets or workflows |

## Dependency rules

`workbench/bootstrap.py` is the only composition root allowed to know concrete implementations across all features.

| Consumer | Allowed production dependencies |
| --- | --- |
| `localization` | standard library |
| `platform` | standard library, PyQt or platform libraries required by the adapter |
| `ui` | `localization`, PyQt |
| `annotations/domain` | standard library only |
| `annotations/application` | `annotations/domain` and consumer-owned protocols |
| `annotations/infrastructure` | `annotations/domain`, declared annotation application ports, standard filesystem/XML/JSON libraries |
| `annotations/ui` | public `annotations`, `localization`, shared `ui`, PyQt |
| `canvas` | public `annotations` values, `localization`, shared `ui`, PyQt |
| `files/application` | public `annotations`, `files/model`, consumer-owned platform protocols |
| `files/infrastructure` | `files/model`, `platform`, filesystem libraries |
| `files/ui` | public `files`, public read-only annotation states, `localization`, shared `ui`, PyQt |
| `image_tools/domain` | standard library and numerical libraries only where the algorithm requires them |
| `image_tools/application` | public `image_tools/domain`, public `annotations`, public `files` recovery contracts, declared infrastructure ports |
| `image_tools/infrastructure` | image-processing application ports, OpenCV, NumPy, Pillow, filesystem libraries |
| `image_tools/ui` | public `image_tools`, `localization`, shared `ui`, PyQt |
| `workbench` | public exports from every feature; concrete implementations only in `bootstrap.py` |

Additional rules:

- another feature is imported only through its package public exports;
- feature-internal modules are not imported across a feature boundary;
- domain and application modules do not import PyQt, widgets, dialogs, or Qt threads;
- production modules do not import `workbench.main_window`;
- no wildcard imports;
- no global service locator, global event bus, or hidden singleton container;
- a dependency-inversion `Protocol` belongs to the consumer that needs the capability;
- direct `Path` and `os` use is acceptable inside infrastructure; interfaces are introduced at meaningful transaction or test boundaries, not around every filesystem call.

## Public package interfaces

Feature `__init__.py` files expose only cross-feature contracts. Example:

```python
from labelimg.annotations import (
    AnnotationBox,
    AnnotationDocument,
    AnnotationFormat,
    AnnotationWorkspace,
    AnnotationEditService,
)
```

These exports are stable internal architecture contracts for this repository, not a promise that LabelImg Enhanced is a general third-party SDK. Tests for a feature may import its internals for white-box coverage; production code in another feature may not.

The externally observable launch boundary becomes:

```toml
[project.scripts]
labelImg = "labelimg.workbench.bootstrap:main"
```

`labelimg.__main__` calls the same bootstrap. `labelimg.app` is deleted.

## Annotation and Canvas boundary

The annotation domain gains an immutable, Qt-free value model. The final field set must preserve every currently serialized or history-relevant value, including stable session identity and ordering.

```python
@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class AnnotationBox:
    instance_id: str
    label: str
    points: tuple[Point, ...]
    difficult: bool
    visible: bool
```

Format adapters, histories, saves, review workflows, and geometry-changing image tools operate on `AnnotationBox` or immutable annotation snapshots. Canvas retains a mutable, Qt-oriented `Shape` for interactive rendering. `annotations.ui.canvas_adapter` performs the only `AnnotationBox <-> Shape` conversion. This adapter belongs to the annotation UI because it projects annotation values into Canvas values; Canvas therefore has no dependency back to annotations.

## State ownership

| State | Authoritative owner | Projections |
| --- | --- | --- |
| current image and transition readiness | `WorkbenchSession` | window title, counter, current-row marker |
| annotation documents, formats and resource mapping | `AnnotationWorkspace` | format selector, candidate labels, file status |
| revisions, Undo/Redo and dirty baseline | annotation editing/history | actions, Canvas scene, dirty indicator |
| transient geometry, hover and Canvas selection | `Canvas` | label-list highlight and action capabilities |
| file sort, filter and batch selection | files feature | file-list widgets and command states |
| image-processing plans and recovery | `ImageProcessingSession` | dialogs, quality badges, recovery UI |
| window geometry, docks and user preferences | platform settings | widgets and actions |

Qt `enabled`, `checked`, text, badges, and list rows are projections. They are never a second source of domain truth.

## Control flow

1. A Widget emits a typed Qt signal representing user intent.
2. A feature UI adapter collects any UI-only input or confirmation.
3. It calls a public feature use case directly.
4. The use case returns an immutable success, conflict, partial-success, confirmation-required, or recovery-limited outcome.
5. The UI adapter presents messages and projects the returned state.
6. Cross-feature navigation and close operations ask `WorkbenchSession` for transition readiness, then invoke feature services in explicit order.

There is no string event bus. A service does not find `MainWindow`, call another feature's Widget, or show `QMessageBox`.

## MainWindow completion rule

`MainWindow` retains only top-level layout, lifecycle events, cross-feature signal wiring, and window-level projections. Approximately 1,000–1,500 lines and a constructor around 150 lines are review warnings rather than hard correctness metrics. A method stays only when its responsibility genuinely belongs to the top-level window.

### MainWindow method migration

The following list accounts for the current 225 methods/accessors by destination. Individual private method names may disappear when a feature service replaces the procedure; the behavior remains covered by regressions.

#### `workbench/main_window.py`

`__init__`, `keyReleaseEvent`, `keyPressEvent`, `eventFilter`, `toggle_actions`, `queue_event`, `status`, `resizeEvent`, `closeEvent`, `error_message`.

The constructor delegates dependency creation to bootstrap, feature command creation to `commands`, and feature UI construction to feature adapters.

#### `workbench/commands.py`

`update_file_menu`, `update_image_menu`, `toggle_paint_labels_option`, `toggle_draw_square`.

Action construction, menus, shortcuts, tooltip/status copy, translation specifications, and top/left command surfaces move here from the constructor.

#### `workbench/session.py`, `navigation.py`, and `lifecycle.py`

`_annotation_image_data`, `system_trash` (getter and setter), `default_save_dir` (getter and setter), `reset_state`, `current_item`, `add_recent_file`, `_cancel_annotation_edit_for_navigation`, `_cancel_pending_drawing`, `_resolve_crop_before_leave`, `open_selected_file`, `open_file_list_path`, `load_file`, `_ensure_active_annotation_choice`, `counter_str`, `show_bounding_box_from_annotation_file`, `_resolve_conflicts_for_close`, `_load_external_resource_conflict`, `_overwrite_resource_conflict`, `load_recent`, `scan_all_images`, `_sync_annotation_directory_ui`, `_switch_annotation_directory`, `change_save_dir_dialog`, `use_image_directory_for_annotations`, `open_annotation_dialog`, `open_dir_dialog`, `import_dir_images`, `populate_file_list`, `open_prev_image`, `open_next_image`, `open_file`, `save_file`, `save_file_as`, `save_file_dialog`, `_save_file`, `close_file`, `delete_image`, `reset_all`, `may_continue`, `_save_history_views`, `_discard_history_view`, `discard_changes_dialog`, `current_path`.

UI-only prompts remain in navigation/lifecycle UI adapters; readiness and transition state live in Qt-free `WorkbenchSession`.

#### `localization/runtime.py` and workbench localization projection

`change_language`, `retranslate_ui`.

The runtime owns language state; each feature adapter retranslates its own widgets. The window only triggers top-level projection.

#### `annotations/application` and `annotations/ui/controller.py`

`set_format`, `change_format`, `set_annotation_format`, `no_shapes`, `_current_annotation_target`, `_activate_annotation_history`, `_history_projection_request`, `_project_annotation_history`, `_annotation_projection_degraded`, `_begin_annotation_gesture`, `_finish_annotation_gesture`, `_cancel_annotation_gesture`, `_annotation_drawing_state_changed`, `_after_annotation_edit`, `_perform_annotation_edit`, `_sync_annotation_history_ui`, `_rebase_current_history`, `_annotation_baseline`, `_history_action_text`, `undo_annotation`, `redo_annotation`, `set_dirty`, `_legacy_shape_moved`, `save_dirty_annotations`, `set_clean`, `_project_review_recovery`, `pop_label_group_menu`, `pop_label_list_menu`, `isolate_label_group`, `delete_annotation_shapes`, `file_annotation_state`, `file_review_state`, `set_selected_review_state`, `set_current_review_state`, `_set_review_state`, `annotation_document_for_path`, `save_current_annotations_directly`, `edit_label`, `edit_shape_label`, `edit_label_group`, `button_state`, `shape_selection_changed`, `canvas_hover_shape_changed`, `label_hover_changed`, `selected_label_shapes`, `label_selection_requested`, `label_visibility_requested`, `update_selection_actions`, `add_label`, `remove_label`, `shape_from_annotation`, `load_labels`, `load_annotation_document`, `update_combo_box`, `save_labels`, `_handle_annotation_storage_conflict`, `_resource_key`, `combo_selection_changed`, `label_selection_changed`, `label_item_changed`, `new_shape`, `annotation_path_for_image`, `annotation_paths_for_image`, `file_persistence_flags`, `refresh_candidate_labels`, `load_candidate_labels_from_dir`, `verify_image`, `question_image`, `toggle_image_status`, `load_predefined_classes`, `load_annotation_by_filename`, `format_shape_for_clipboard`, `clear_current_labels`, `copy_current_bounding_boxes`, `paste_copied_bounding_boxes`, `copy_previous_bounding_boxes`.

Review and history mutations move to application services. Dialogs and label-list projections move to annotation UI. `shape_from_annotation` and `load_labels` are replaced by the Canvas annotation adapter rather than retained as domain methods.

#### `files/application` and `files/ui/controller.py`

`selected_file_paths`, `visible_file_paths`, `show_file_list_filter`, `apply_file_list_view`, `update_file_navigation_actions`, `_adjacent_visible_file`, `update_file_selection_count`, `update_current_file_marker`, `pop_file_list_menu`, `invert_file_selection`, `_select_files_by_role`, `select_files_by_annotation_state`, `select_files_by_review_state`, `copy_selected_file_paths`, `reveal_selected_file`, `clear_selected_file_annotations`, `delete_selected_files`, `delete_file_paths`, `_warn_manual_trash_recovery`, `run_file_operation`, `rebuild_file_list_after_deletion`, `rescan_annotation_workspace`, `report_file_operation_result`, `show_file_operation_failures`, `rename_selected_files`, `rename_single_file`, `execute_file_rename`, `file_item_double_clicked`, `file_list_display_path`, `file_list_item_text`, `update_file_list_item_status`, `refresh_file_list_statuses`.

Annotation-aware effects call the annotations public interface. The files UI never reaches into annotation implementation modules.

#### `canvas` and its workbench bridge

`create_shape`, `toggle_drawing_sensitive`, `set_edit_mode`, `set_pan_mode`, `copy_selected_shape`, `scroll_request`, `pan_request`, `set_zoom`, `add_zoom`, `zoom_request`, `set_fit_window`, `set_fit_width`, `toggle_polygons`, `toggle_all_annotations`, `paint_canvas`, `adjust_scale`, `scale_fit_window`, `scale_fit_width`, `choose_color1`, `delete_selected_shape`, `choose_shape_line_color`, `choose_shape_fill_color`, `copy_shape`, `move_shape`.

Canvas owns transient state and emits typed intents. Annotation mutations still pass through the annotation edit service.

#### `image_tools/ui/controller.py` and image-tool services

`_project_image_processing`, `open_transform_image`, `_apply_geometry_transform_batch`, `open_adjust_image`, `open_image_quality_check`, `_run_image_quality_request`, `_start_image_quality_scan`, `_complete_image_quality_scan`, `_apply_image_quality_results`, `_fail_image_quality_scan`, `_cancel_image_quality_scan`, `_cleanup_image_quality_scan`, `refresh_image_quality`, `clear_image_quality_results`, `quick_transform_current_image`, `enter_crop_mode`, `cancel_crop`, `apply_crop`, `_finish_crop_mode`, `open_remove_colored_frames`, `undo_last_image_processing`, `_latest_image_processing_recovery`, `_choose_image_recovery_paths`, `_invalidate_image_quality`, `_quality_result_for_path`, `_refresh_current_image_pixels`.

Qt threads and dialogs remain in image-tool UI; algorithms, planning, commit, and recovery remain Qt-free application/infrastructure behavior.

#### `workbench/recovery_ui.py`

`open_file_recovery_center`, `_confirm_file_recovery`.

This adapter presents the combined recovery surface while dispatching to the public file or image-processing recovery contract.

#### Help UI

`show_tutorial_dialog`, `show_default_tutorial_dialog`, `show_info_dialog`, `show_shortcuts_dialog` remain small workbench UI functions or a small help module if their size justifies it.

## Production file migration

| Current file | Target or disposition |
| --- | --- |
| `labelimg/__init__.py` | remains; version and deliberately small package metadata only |
| `labelimg/__main__.py` | remains; delegates to `workbench.bootstrap.main` |
| `labelimg/app.py` | split across `workbench`, feature UI controllers, and Canvas adapter; deleted |
| `labelimg/annotation_document.py` | `annotations/domain/model.py` plus format ports |
| `labelimg/annotation_history.py` | `annotations/domain/history.py` |
| `labelimg/annotation_editing.py` | `annotations/application/editing.py` |
| `labelimg/annotation_workspace.py` | `annotations/application/workspace.py` |
| `labelimg/annotation_persistence.py` | `annotations/application/persistence.py` |
| `labelimg/annotation_review.py` | `annotations/application/review.py` |
| `labelimg/annotation_session.py` | `annotations/application/session.py` |
| `labelimg/annotation_storage.py` | `annotations/infrastructure/storage.py` |
| `labelimg/pascal_voc_io.py` | `annotations/infrastructure/formats/pascal_voc.py` |
| `labelimg/yolo_io.py` | `annotations/infrastructure/formats/yolo.py` |
| `labelimg/create_ml_io.py` | `annotations/infrastructure/formats/create_ml.py` |
| `labelimg/create_ml_collection.py` | `annotations/infrastructure/formats/create_ml_collection.py` |
| `labelimg/candidate_label_dialog.py` | `annotations/ui/candidate_label_dialog.py` |
| `labelimg/label_group_list.py` | `annotations/ui/label_group_list.py` |
| label-list classes inside `app.py` | `annotations/ui/label_list.py` |
| `labelimg/canvas.py` | `canvas/widget.py` |
| `labelimg/shape.py` | `canvas/shape.py` |
| `labelimg/selection.py` | `canvas/selection.py` |
| `labelimg/canvas_interaction.py` | `canvas/interaction.py` |
| Canvas/annotation conversions inside `app.py` | `annotations/ui/canvas_adapter.py` |
| Canvas distance helpers in `utils.py` | `canvas/geometry.py` |
| `labelimg/file_list.py` | split into `files/ui/list_widget.py`, `filter_panel.py`, `rename_dialog.py`, and file view-state types |
| `labelimg/file_operations.py` | split into `files/application/operations.py` and `files/infrastructure/filesystem.py` |
| `labelimg/file_operation_transaction.py` | `files/application/transaction.py` |
| `labelimg/file_recovery.py` | `files/application/recovery.py` plus public recovery values in `files/model.py` |
| `labelimg/windows_trash.py` | `platform/trash.py` |
| `labelimg/image_tools/session.py` | `image_tools/application/session.py` |
| `labelimg/image_tools/adjustment.py` | `image_tools/application/adjustment.py` |
| `labelimg/image_tools/crop.py` | `image_tools/application/crop.py` |
| `labelimg/image_tools/crop_annotation.py` | `image_tools/application/crop_annotations.py` |
| `labelimg/image_tools/geometry_transform.py` | `image_tools/application/geometry_transform.py` |
| `labelimg/image_tools/image_tool_processor.py` | `image_tools/application/colored_frame_processor.py` |
| `labelimg/image_tools/quality.py` | split into `image_tools/domain/quality.py` and `application/quality_scan.py` |
| `labelimg/image_tools/crop_geometry.py` | `image_tools/domain/crop_geometry.py` |
| `labelimg/image_tools/colored_frame_removal.py` | `image_tools/domain/colored_frame_removal.py` |
| `labelimg/image_tools/image_file_codec.py` | `image_tools/infrastructure/image_codec.py` |
| `labelimg/image_tools/recoverable_replacement.py` | `image_tools/infrastructure/recoverable_replacement.py` |
| `labelimg/image_tools/adjustment_dialog.py` | `image_tools/ui/adjustment_dialog.py` |
| `labelimg/image_tools/crop_ui.py` | `image_tools/ui/crop_overlay.py` |
| `labelimg/image_tools/geometry_dialog.py` | `image_tools/ui/geometry_dialog.py` |
| `labelimg/image_tools/quality_ui.py` | `image_tools/ui/quality_panel.py` |
| `labelimg/image_tools/dialog.py` | `image_tools/ui/colored_frame_dialog.py` |
| `labelimg/image_tools/recovery_dialog.py` | `image_tools/ui/recovery_dialog.py` |
| `labelimg/image_tools/__init__.py` | replaced by explicit public feature exports |
| `labelimg/i18n.py` | `localization/runtime.py` |
| `labelimg/translations.py` | `localization/catalogs.py` |
| `labelimg/stringBundle.py` | deleted; historical compatibility facade is intentionally removed |
| `labelimg/settings.py` | `platform/settings.py` |
| `labelimg/constants.py` | deleted; settings keys move to `platform/settings_keys.py`, format identity uses annotation enums, encoding constants are colocated with format infrastructure |
| `labelimg/utils.py` | deleted; action/icon helpers move to `ui`, label helpers to `annotations/ui`, geometry to `canvas`, sorting to its owning feature, obsolete Qt4 helpers disappear |
| `labelimg/ustr.py` | deleted; Python 3 `str` and explicit decoding replace the legacy helper |
| `labelimg/command_surfaces.py` | `workbench/commands.py` |
| `labelimg/colorDialog.py` | `ui/color_dialog.py` |
| `labelimg/toolBar.py` | `ui/tool_bar.py` |
| `labelimg/resources.py` | regenerated as `ui/generated_resources.py` |
| `labelimg/combobox.py` | deleted after confirming no production use |
| `labelimg/hashableQListWidgetItem.py` | deleted after confirming no production use |
| `labelimg/zoomWidget.py` | deleted after confirming no production use; current ZoomControl remains feature-owned |

`labelimg/data/app.ico` and `predefined_classes.txt` remain package data unless a separate product decision removes the predefined-class workflow. Candidate labels continue to derive only from saved annotation-directory documents.

## Test migration

`tools/run_tests.py` changes from a root-only `glob("test_*.py")` to recursive discovery while preserving one test file per child process and the isolated `LABELIMG_CONFIG_DIR` behavior.

| Target test area | Current tests |
| --- | --- |
| `tests/annotations` | `test_annotation_document`, `test_annotation_editing`, `test_annotation_history`, `test_annotation_persistence`, `test_annotation_review`, `test_annotation_storage`, `test_annotation_workspace`, `test_create_ml_collection`, `test_io`, `test_label_dialog_sorting`, `test_label_group_list`, `test_label_list_sorting`, domain portions of `test_save_dir_candidate_labels` |
| `tests/canvas` | `test_canvas_interaction`, `test_multi_shape_selection`, `test_overlapping_shape_vertex_drag`, `test_selection_set`, `test_shape_rendering_style` |
| `tests/files` | `test_file_list_annotation_status`, `test_file_list_selection`, `test_file_list_sorting`, `test_file_list_view`, `test_file_operations`, `test_file_recovery` |
| `tests/image_tools` | `test_colored_frame_removal`, `test_geometry_transform_dialog`, `test_image_adjustment_dialog`, `test_image_adjustment_processor`, `test_image_crop_overlay`, `test_image_crop`, `test_image_file_codec`, `test_image_geometry_transform`, `test_image_processing_recovery`, `test_image_processing_session`, `test_image_processing_transaction`, `test_image_quality_ui`, `test_image_quality`, `test_image_recovery_dialog`, `test_image_tool_processor`, `test_image_tools_app`, `test_image_tools_dialog`, `test_recoverable_image_replacement` |
| `tests/localization` | `test_i18n`; `test_stringBundle` is replaced by runtime/catalog tests rather than preserving the removed facade |
| `tests/platform` | `test_settings`, `test_windows_trash` |
| `tests/ui` | feature-relevant portions of `test_utils`; common action/icon tests only |
| `tests/workbench` | `test_command_surfaces`, `test_delete_image_navigation`, `test_file_entry_ui`, `test_qt`, `test_realtime_auto_save`, integration portions of `test_save_dir_candidate_labels`, `test_ui_copy` |
| `tests/packaging` | `test_app_icon_assets`, wheel inventory, console/module entry, generated-resource import and old-module absence |
| `tests/architecture` | public-export rules, allowed imports, cycles, banned dependencies, wildcard imports, old paths and concrete-main-window imports |

Tests importing `MainWindow` are retained only for real top-level integration behavior. Feature behavior moves to tests against public feature interfaces or local UI adapters.

## Architecture checks

Repository-owned AST tests enforce:

1. the declared feature dependency graph has no cycle;
2. cross-feature production imports target only public exports;
3. annotation and image-tool domain/application modules do not import PyQt;
4. OpenCV, NumPy, and Pillow occur only in approved image-tool algorithm/infrastructure boundaries;
5. no production module imports `workbench.main_window` except bootstrap and entry tests where explicitly allowed;
6. no wildcard imports;
7. no old root module remains or is referenced;
8. every feature `__all__` matches its approved public contract;
9. generated resources are imported only through the UI resource boundary;
10. test discovery covers nested test directories.

## Migration phases

Each phase updates source and its tests together and ends green. No committed or handoff-ready checkpoint contains forwarding modules or parallel old/new import paths.

### Phase 0: baseline

- run and record the full source suite;
- build and inspect a baseline wheel;
- record package files, public entry behavior, settings behavior, and source/installed parity;
- add missing characterization tests for observable behavior before moving it.

### Phase 1: scaffolding and leaf boundaries

- create feature packages and explicit exports;
- introduce recursive isolated test discovery and architecture test infrastructure;
- migrate localization, platform adapters, generated resources, and shared UI primitives;
- eliminate wildcard imports and dead legacy widgets.

### Phase 2: Qt-free annotation values and Canvas

- introduce `Point`, `AnnotationBox`, and immutable conversion tests;
- make annotation documents and histories independent of Canvas `Shape`;
- add the Canvas annotation adapter;
- migrate Canvas, Shape, selection, interaction, and Canvas tests.

### Phase 3: annotations

- migrate domain, application, storage, and all format adapters;
- migrate annotation-specific widgets;
- update public exports and annotation tests;
- delete the corresponding root modules immediately after imports are updated.

### Phase 4: files

- split UI, application transactions, recovery values, filesystem mechanics, and platform trash;
- migrate file-list and file-operation tests;
- preserve partial success, atomicity, recovery identities, and annotation awareness.

### Phase 5: image tools

- split algorithms, use cases, codecs/replacement, and Qt UI;
- keep numerical dependencies inside approved boundaries;
- preserve geometry-changing annotation commits and recovery semantics.

### Phase 6: workbench and MainWindow

- create `WorkbenchSession`, navigation, lifecycle, recovery UI, and command construction;
- move all feature workflows to feature adapters;
- reduce `MainWindow` to shell responsibilities;
- change the console entry and module entry;
- delete `labelimg.app`.

### Phase 7: cleanup and release

- delete all obsolete root modules, aliases, Qt4 branches, generic constants/utilities, and stale tests;
- update README, contributor guidance, CHANGELOG, package metadata, and version to `2.0.0`;
- regenerate resources and build artifacts from clean inputs.

## Verification gates

Every phase:

- focused migrated-feature tests pass;
- all architecture tests pass;
- full source suite passes with offscreen Qt and isolated configuration;
- `git diff --check` passes;
- no unrelated worktree content is overwritten.

Final source gate:

- every production/test file is in its accepted feature package;
- all 225 current MainWindow responsibilities are either shell responsibilities or covered by a feature owner;
- no old module path or forwarding shim exists;
- no forbidden dependency or import cycle exists;
- visible behavior regression suites pass;
- command help and `python -m labelimg --help` agree.

Packaging gate:

- build from a clean repository-local build directory;
- inspect wheel contents for target packages, data, generated resources, and absence of stale legacy modules;
- install into an isolated target and run the complete recursive installed-package suite;
- verify console and module entry points;
- verify source/wheel payload parity where applicable.

DL deployment gate:

- close or otherwise avoid disturbing a user-owned running LabelImg process;
- install the verified wheel into the exact DL Conda environment;
- run `pip check`, launcher help, installed-package tests, generated-resource checks, and source/installed parity;
- report any restart boundary explicitly.

## Rollback and Git policy

Implementation begins on `codex/modular-monolith-refactor` from the current `e149661` lineage after final confirmation. The assistant does not commit or push without a later explicit request. Phase checkpoints are verified working-tree states; reviewable commits may be created later at the user's direction.

DL deployment occurs only after isolated wheel validation. The previously installed verified wheel or package backup is retained until installed validation succeeds. No running user process is killed merely to make installation convenient.

## Non-goals

- no UI redesign or new shortcut;
- no behavior or data-format change;
- no plugin system, microservices, event bus, DI framework, or generic application framework;
- no permanent compatibility aliases;
- no public general-purpose Python SDK commitment;
- no opportunistic feature work during structural moves;
- no architecture judged solely by line-count targets.

## Decision status

All architecture branches described here are resolved. The user authorized full implementation and waived further questions for conclusions that follow established engineering practice.

### 2026-08-12 deepening checkpoint

The implementation now makes the following seams executable rather than aspirational:

- `FileListProjection` owns immutable row facts, sorting, filtering, visible navigation, and deterministic adjacency; the Qt control state is only a mutable query adapter.
- `CanvasInteractionSnapshot` is immutable and all selection, right-button targeting, and hover changes pass through `CanvasInteraction` transitions; Canvas no longer exposes writable forwarding properties for transient gesture state.
- file operations and image processing use separate transaction and recovery ledgers. Shared trash identities/statuses live in `platform.recovery`; `files` no longer imports image-tool implementations.
- `WorkbenchSession` owns ordered transition requirements and issues source/target/revision-bound single-use tickets after crop, edit, conflict, and dirty-history requirements are resolved.
- `workbench.bootstrap` owns CLI parsing, typed launch options, concrete window construction, and process startup. `WorkbenchComposer` is called explicitly and is not a `MainWindow` mixin.
- `annotations`, `canvas`, `files`, and `image_tools` form an acyclic feature graph and cross-feature production imports use package public exports. Architecture tests enforce the graph, public exports, composition root, Qt-free layers, numeric dependency ownership, and legacy-path absence.

### 2026-08-12 deepening closure

- current-image identity no longer has a writable `MainWindow.file_path` projection or a `WorkbenchSession.replace_active` bypass. Every replacement consumes a source/target/revision-bound transition ticket through `WorkbenchSession`.
- `MainWindow` constructs only its Qt base. `workbench.bootstrap.create_workbench` is now required to apply the concrete `WorkbenchComposer`; tests and production startup cross the same composition interface.
- the recovery workbench consumes file and image-processing outcomes through feature public exports, while feature-neutral resource fingerprints live in `platform.recovery` without a dependency on annotation infrastructure.
- `FileListViewState` exposes only the immutable `FileListProjection` interface. The old callback-heavy `ordered_paths`, `matches`, and `visible_paths` compatibility queries and the controller navigation fallback are removed.
- Canvas hover is observed through `CanvasInteractionSnapshot` and changed through one signal-aware transition method. Writable `h_shape`, `h_vertex`, and `h_edge` compatibility properties are removed.
