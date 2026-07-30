# Use pyproject, setuptools, and a src layout

LabelImg Enhanced will use `pyproject.toml` as the single packaging configuration, retain `setuptools` as the build backend, and place importable code under `src/labelimg/`. This modernizes packaging and prevents accidental imports from the repository root without combining the migration with an unnecessary build-tool change.
