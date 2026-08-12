---
status: accepted
---

# Enforce feature boundaries with architecture tests

Feature ownership and dependency direction will be executable constraints rather than documentation alone. Repository-owned tests built with Python's standard `ast` module will reject cross-feature imports that bypass public package exports, cycles in the feature dependency graph, PyQt dependencies in domain or application modules, image-processing libraries outside approved boundaries, wildcard imports, production dependencies on the concrete main window, legacy module paths, and undeclared public exports. The test tree will mirror production feature packages, with cross-feature Qt flows under `workbench`, import rules under `architecture`, and wheel entry/resource checks under `packaging`; the existing isolated-per-file Qt execution behavior will be retained. A third-party import-linting framework is deferred until the local rules become materially harder to maintain.
