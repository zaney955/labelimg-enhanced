---
status: accepted
---

# Migrate internal module paths without compatibility shims

The architecture refactor will preserve all observable LabelImg behavior, data formats, settings, recovery semantics, and documented launch commands while reorganizing the complete production and test codebase. Existing internal imports such as `labelimg.app`, `labelimg.annotation_document`, and `labelimg.file_operations` will migrate directly to their new package-owned paths without forwarding modules or a compatibility period; only the observable `labelImg` command and `python -m labelimg` behavior remain compatibility boundaries. This accepts a deliberate Python import break so the package root can become a real architectural boundary instead of retaining permanent legacy aliases.
