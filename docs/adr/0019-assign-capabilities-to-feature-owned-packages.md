---
status: accepted
---

# Assign capabilities to feature-owned packages

The package will be divided into `workbench`, `annotations`, `files`, `canvas`, `image_tools`, `localization`, `platform`, and a deliberately small shared `ui` package. Annotation formats and annotation-specific widgets belong to `annotations`; file-list widgets and filesystem workflows belong to `files`; canvas selection and interaction belong to `canvas`; only genuinely cross-feature Qt primitives belong to `ui`. Physical `domain`, `application`, `infrastructure`, and `ui` subpackages will be introduced where feature size justifies them rather than mechanically for every feature. Cross-feature navigation and close readiness will be represented by a Qt-free `WorkbenchSession`, while feature services retain ownership of their own transactions. Production code may consume another feature only through that feature package's declared public exports; `workbench/bootstrap.py` is the sole composition root permitted to know concrete implementations across all features.
