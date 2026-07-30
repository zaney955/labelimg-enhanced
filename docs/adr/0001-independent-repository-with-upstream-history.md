# Maintain an independent repository with upstream history

This LabelImg derivative will live in a new user-owned GitHub repository rather than a GitHub fork, while retaining the original LabelImg Git history. The user-owned repository will be the writable `origin`, and the original LabelImg repository will remain a read-only `upstream`; this preserves provenance and comparison with upstream while allowing independent maintenance, releases, and repository governance.
