---
status: accepted
---

# Organize the application as a feature-first modular monolith

LabelImg Enhanced will be organized as a feature-first modular monolith. Each feature package will keep its domain policy, application coordination, infrastructure adapters, and Qt presentation concerns behind an explicit public boundary; domain and application code must not depend on Qt, UI packages, or another feature's private implementation. `MainWindow` remains the thin Qt shell and composition root for top-level widgets, cross-feature signal wiring, window-state projection, and lifecycle events, while filesystem transactions, annotation policy, image processing, review state, and other workflows move behind feature-owned interfaces. Automated architecture tests will enforce the dependency directions and constrain OpenCV, NumPy, and Pillow to image-processing boundaries.
