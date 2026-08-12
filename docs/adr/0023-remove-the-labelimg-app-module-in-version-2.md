---
status: accepted
---

# Remove the labelimg.app module in version 2

The modular-monolith migration will be released as LabelImg Enhanced `2.0.0` because it deliberately removes every historical internal Python import path, including `labelimg.app`. The console script will target `labelimg.workbench.bootstrap:main`, `python -m labelimg` will call the same bootstrap, and their command-line and visible application behavior will remain unchanged; `MainWindow` moves to `labelimg.workbench.main_window` without becoming a promised third-party API. A major-version release makes the intentional package-level incompatibility explicit even though end-user workflows remain stable.
