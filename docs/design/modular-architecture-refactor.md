# LabelImg Enhanced modular architecture

Status: the version 2 package migration is implemented. This page describes current module ownership, interfaces, and remaining architecture constraints; the migration rationale is recorded in [ADRs 0017–0023](../README.md).

## Outcome

LabelImg Enhanced is a feature-first modular monolith: one Python distribution and one application process, launched through `labelImg` or `python -m labelimg`. The annotation workbench is the main window; the update center is an independent application window within the same process.

The package root contains only entry and metadata modules plus feature packages and data. Historical imports such as `labelimg.app` are removed without forwarding aliases. Public feature exports are repository-internal interfaces, not a third-party SDK promise.

## Feature ownership

| Module | Owns | Starting point |
| --- | --- | --- |
| `workbench` | Launch, concrete composition, current-image transitions, cross-feature coordination, and window projections | [bootstrap](../../src/labelimg/workbench/bootstrap.py), [session](../../src/labelimg/workbench/session.py) |
| `annotations` | Documents, format interpretation, history, saving, review, workspace resource identity, and annotation UI | [public interface](../../src/labelimg/annotations/__init__.py) |
| `files` | Discovery, file-list projection and selection, annotation-aware file operations, and file recovery | [public interface](../../src/labelimg/files/__init__.py) |
| `canvas` | Interactive shapes, geometry, selection, hover, hit testing, and viewport interaction | [public interface](../../src/labelimg/canvas/__init__.py) |
| `image_tools` | Image algorithms, processing plans, atomic replacement and recovery, quality analysis, display adjustments, and their UI | [public interface](../../src/labelimg/image_tools/__init__.py) |
| `updates` | Stable-release checks, distribution strategy, installer validation, and the update center | [public interface](../../src/labelimg/updates/__init__.py), [ADR 0026](../adr/0026-check-stable-releases-without-self-modifying-python-installs.md), [ADR 0027](../adr/0027-install-unsigned-managed-windows-updates-explicitly.md) |
| `localization` | Language state, translation catalogs, and Qt text adapters | [runtime](../../src/labelimg/localization/runtime.py) |
| `platform` | Settings, OS trash adapters, and feature-neutral recovery identities and fingerprints | [settings](../../src/labelimg/platform/settings.py), [recovery](../../src/labelimg/platform/recovery.py) |
| `ui` | Shared Qt primitives and generated resources | [package](../../src/labelimg/ui/) |

Features introduce `domain`, `application`, `infrastructure`, and `ui` subpackages where their size requires them. No generic `common`, `core`, or `utils` package is used. Domain terminology is maintained in [CONTEXT.md](../../CONTEXT.md).

## Dependency rules

The accepted design uses consumer-owned interfaces, explicit calls, and constructor injection. Domain and application modules stay free of Qt; UI adapters own widgets, prompts, Qt workers, and projection. OpenCV, NumPy, and Pillow belong to `image_tools`. Business features consume one another through public package exports and form an acyclic dependency graph.

`workbench.bootstrap.create_workbench` constructs `MainWindow` and explicitly invokes [WorkbenchComposer](../../src/labelimg/workbench/composition.py). Only bootstrap imports the concrete window and composer. The composer is not a window mixin. This is the composition arrangement established by [ADR 0019](../adr/0019-assign-capabilities-to-feature-owned-packages.md) and [ADR 0021](../adr/0021-keep-domain-models-and-use-cases-free-of-qt.md), refining ADR 0018's earlier description of `MainWindow` as the composition root.

The intended workbench interface remains broader than current enforcement: `MainWindow` and its composer still import feature internals. The architecture tests enforce public exports and acyclicity between `annotations`, `canvas`, `files`, `image_tools`, and `updates`; they do not prove that every workbench import uses a public export. The thin-window goal remains a responsibility constraint, not a completed line-count target.

No wildcard imports, global event bus, service locator, or singleton dependency container is allowed. Infrastructure may use filesystem operations directly; an interface is introduced around a meaningful capability or transaction seam rather than every individual call.

## Annotation and Canvas boundary

[AnnotationBox](../../src/labelimg/annotations/domain/model.py) and [history snapshots](../../src/labelimg/annotations/domain/history.py) are immutable Qt-free values. `AnnotationDocument` is the mutable document model; history snapshots retain editing identity and presentation state separately from serialized box values.

Canvas retains mutable Qt-oriented `Shape` objects. [annotations.ui.canvas_adapter](../../src/labelimg/annotations/ui/canvas_adapter.py) performs document/shape conversion, so annotation UI depends on the Canvas public interface. Canvas does not own saved-document identity, persistence, or history policy. Geometry-changing image tools use annotation values and coordinate the resulting image and annotation state through the image-processing interface.

## State ownership

| State | Authoritative owner | UI projection |
| --- | --- | --- |
| Current image and transition readiness | `WorkbenchSession` | Window title, image counter, current-file marker |
| Documents, active format, and resource mapping | `AnnotationWorkspace` | Format selector, candidate labels, file status |
| Revisions and saved baseline | Annotation editing and `AnnotationHistory` | Undo/Redo, Canvas scene, dirty indicator |
| Transient geometry, hover, and Canvas selection | Canvas and `CanvasInteraction` | Label highlight and action availability |
| File sort, filter, and visible navigation | `FileListProjection` | File-list rows and navigation actions |
| File batch selection | Files UI | Selected rows and selection count, independent of current image |
| Processing plans and recovery | `ImageProcessingSession` | Image dialogs, quality findings, recovery UI |
| Persistent preferences | Platform settings | Window geometry, docks, and actions |

Qt action flags, text, and rows are projections. `CanvasInteractionSnapshot` exposes transient interaction state without writable hover compatibility properties. `FileListProjection` provides immutable row facts and deterministic visible adjacency; obsolete callback-based view queries are removed.

## Control flow

1. A widget emits user intent through a Qt signal.
2. The UI adapter collects input, calls the owning module, and presents its result.
3. Expected conflicts, partial success, and recovery limitations cross the interface as structured outcomes; UI code decides how to display them.
4. Cross-feature navigation plans a transition through `WorkbenchSession`, resolving crop, open annotation edits, external conflicts, and dirty annotations in order.
5. An authorized transition consumes a single-use ticket bound to source image, target image, and session revision. Stale or reused tickets cannot replace the current image.

File operations and image processing retain separate transaction and recovery ledgers. The [recovery workbench](../../src/labelimg/workbench/recovery_ui.py) coordinates their public interfaces; shared trash identities and fingerprints live in `platform.recovery`.

## Behavior invariants

Structural changes preserve observable launch commands, settings keys, format interpretation, edit history, dirty baselines, external conflicts, and recovery semantics. Subsequent product changes are documented in their owning design or ADR, rather than treated as a permanent freeze of version 2 UI behavior.

- Editing, saves, physical-resource conflicts, and file recovery follow [Undo/Redo and File Recovery](undo-redo-and-file-recovery.md).
- Geometry changes commit and recover images, annotation resources, and live projections together; see [Image Tools](image-tools.md) and [ADR 0015](../adr/0015-commit-geometry-changing-image-tools-with-annotations.md).
- Progressive loading uses session-only indexes and rejects stale generations; see [Large Directory Loading](large-directory-loading.md).
- External synchronization follows [ADR 0025](../adr/0025-synchronize-only-the-current-annotation-document.md): synchronize the current document, refresh affected inactive metadata through lightweight directory events, and leave inactive Canvas/history state untouched. This supersedes the earlier no-watcher rule.
- Python installations never execute their own upgrade command. Managed Windows installation requires explicit user action and ordinary guarded close; see ADRs 0026–0027 above.

## Architecture checks

[tests/architecture/test_dependencies.py](../../tests/architecture/test_dependencies.py) is the executable source for enforced import rules. It checks package-root contents and legacy-path absence, the five-feature public import graph, Qt-free domain/application layers, numeric-library ownership, bootstrap/window composition, recovery coordination, resolvable exports, and the absence of wildcard imports and generic utility packages. These checks do not establish every accepted design constraint by themselves.

Tests follow feature ownership, with integrated Qt flows under `tests/workbench` and package checks under `tests/packaging`. [tools/run_tests.py](../../tools/run_tests.py) discovers nested test files, runs each in a separate process with isolated configuration, and supports installed-package validation through `--installed`. Current setup and validation commands belong in the [README](../../README.en.md#development-and-validation); completed migration phases and deployment transcripts are retained in Git history.
