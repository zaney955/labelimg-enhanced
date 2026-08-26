"""Qt-free policy for stable update discovery and notification timing."""

from labelimg.updates.domain import (
    StableVersion,
    UpdateDecision,
    UpdateDecisionKind,
)


CHECK_INTERVAL_SECONDS = 24 * 60 * 60
SNOOZE_SECONDS = 24 * 60 * 60
MAX_FAILURE_BACKOFF_SECONDS = 7 * CHECK_INTERVAL_SECONDS


def automatic_check_due(enabled, next_check_at, now):
    if not bool(enabled):
        return False
    try:
        deadline = float(next_check_at or 0)
    except (TypeError, ValueError):
        deadline = 0
    return float(now) >= deadline


def next_automatic_check_at(now, failure_count):
    try:
        failures = max(0, int(failure_count))
    except (TypeError, ValueError):
        failures = 0
    delay = min(
        MAX_FAILURE_BACKOFF_SECONDS,
        CHECK_INTERVAL_SECONDS * (2 ** min(failures, 3)),
    )
    return float(now) + delay


def evaluate_update(
    current_version,
    release,
    *,
    ignored_version=None,
    snoozed_until=0,
    now,
):
    current = StableVersion.parse(current_version)
    if release.version <= current:
        return UpdateDecision(UpdateDecisionKind.UP_TO_DATE, release)
    if str(ignored_version or "") == str(release.version):
        return UpdateDecision(UpdateDecisionKind.IGNORED, release)
    try:
        snooze_deadline = float(snoozed_until or 0)
    except (TypeError, ValueError):
        snooze_deadline = 0
    if float(now) < snooze_deadline:
        return UpdateDecision(UpdateDecisionKind.SNOOZED, release)
    return UpdateDecision(UpdateDecisionKind.AVAILABLE, release)

