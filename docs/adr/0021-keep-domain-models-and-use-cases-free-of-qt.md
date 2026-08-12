---
status: accepted
---

# Keep domain models and use cases free of Qt

Annotation documents, histories, persistence, review workflows, and image-geometry use cases will exchange immutable Qt-free annotation values rather than Canvas `Shape` objects. Canvas retains its interaction-oriented `Shape`, and a boundary adapter projects between it and the annotation model; Qt values such as `QPointF`, `QColor`, widgets, dialogs, and threads cannot enter domain or application interfaces. Feature UI adapters connect local widget signals to public use cases without imposing a uniform MVC or MVVM framework. Expected conflicts, partial successes, confirmation requirements, and recovery limitations are returned as structured immutable outcomes; invariant violations use explicit exceptions, and only UI code presents messages. Concrete services and external adapters are wired by ordinary constructor injection in `workbench/bootstrap.py`; global service locators, singleton containers, and a dependency-injection framework are rejected.
