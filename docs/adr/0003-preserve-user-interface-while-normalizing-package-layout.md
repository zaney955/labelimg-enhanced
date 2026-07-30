# Preserve the user interface while normalizing the package layout

The migrated project will keep the `LabelImg` application identity and `labelImg` command, but place Python source under `src/labelimg/` and move the former top-level `libs.*` modules into that package namespace. The new distribution will use an independent name, preserving existing user workflows while removing the collision-prone top-level `libs` package and separating source code from installed artifacts.
