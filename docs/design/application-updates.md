# Application Updates

The update center is one ordinary independent window for checking, availability, downloading, cancellation, failure, and installation readiness. It may be minimized or placed behind the annotation workbench; asynchronous attention raises it without taking Canvas focus. Manual checks activate it and show checking, current-version, or failure feedback, with cancellation while checking and retry after failure. Automatic failures remain silent.

The window uses a compact application header, a state-specific icon, a short status title, and separate version metadata. Current-version success omits duplicate version text. Download progress is a thin track with a separate readable percentage. Failure diagnostics remain verbatim, selectable, and scroll within a bounded region. Each state has one primary action; release-page and ignore-version actions remain secondary links. State, progress, and actions survive live language and theme changes.

## Stable release discovery

The stable update check is read-only and asynchronous. It is enabled by default, may be disabled in Settings, runs automatically at most once every 24 hours with bounded failure backoff, and is available explicitly from Help. Users may defer an available version for 24 hours or ignore exactly that version.

Release discovery, stable-tag validation, version comparison, caching, and the rule against running package managers from Python installations are recorded in [ADR 0026](../adr/0026-check-stable-releases-without-self-modifying-python-installs.md). The [release workflow](../../.github/workflows/release.yml) is the executable source for asset names and build gates; GitHub Release is the distribution record and does not imply PyPI publication.

## Distribution actions

| Distribution strategy | Update-center action |
| --- | --- |
| Source or Python environment | Copy an explicit wheel upgrade command for the user to run |
| Portable frozen build | Open the release page |
| Managed Windows installation | Download and verify the installer; offer explicit installation |

A managed installation requires the executable and exact adjacent current-user Inno marker to share one installation directory. Frozen status alone does not grant installer capability. [ADR 0027](../adr/0027-install-unsigned-managed-windows-updates-explicitly.md) owns the Windows package, integrity checks, explicit installation, licensing obligations, and rollback decision.

## Download and install lifecycle

The update package pairs the versioned Windows x64 installer with its exact `SHA256SUMS` entry from the same release. The checksum manifest is downloaded before streaming the installer into a private temporary directory within a 512 MiB limit. Only a candidate matching the unique manifest entry is retained. SHA-256 establishes integrity relative to that release; the unsigned package has no authenticated Windows publisher identity.

Progress continues while the update center is hidden. Failure, cancellation, and readiness are explicit states. A verified candidate remains inert until Install Now and the workbench's ordinary guarded close both succeed. Installation never bypasses unsaved edits, conflicts, loading, or active-worker checks.

Rollback covers the Inno installation transaction before completion. A successfully installed application is not monitored for post-launch health and is not automatically downgraded or restored to a prior session.

Implementation is under [updates](../../src/labelimg/updates); checks live in [update tests](../../tests/updates) and [release-contract tests](../../tests/packaging/test_release_contract.py).
