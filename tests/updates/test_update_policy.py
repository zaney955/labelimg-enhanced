import unittest

from labelimg.updates import (
    StableRelease,
    StableVersion,
    UpdateDecisionKind,
    automatic_check_due,
    evaluate_update,
    next_automatic_check_at,
)


def release(version):
    parsed = StableVersion.parse(version)
    return StableRelease(
        version=parsed,
        tag_name="v%s" % parsed,
        name="LabelImg Enhanced %s" % parsed,
        summary="A tested stable release.",
        html_url=(
            "https://github.com/zaney955/labelimg-enhanced/releases/tag/v%s"
            % parsed
        ),
        published_at="2026-08-26T00:00:00Z",
        wheel_url=(
            "https://github.com/zaney955/labelimg-enhanced/releases/download/"
            "v%s/labelimg_enhanced-%s-py3-none-any.whl"
            % (parsed, parsed)
        ),
    )


class StableVersionTest(unittest.TestCase):
    def test_compares_numeric_components_instead_of_strings(self):
        self.assertGreater(
            StableVersion.parse("2.10.0"),
            StableVersion.parse("2.9.0"),
        )

    def test_accepts_a_release_tag_but_rejects_non_stable_versions(self):
        self.assertEqual(str(StableVersion.parse("v2.1.0")), "2.1.0")
        for value in ("2.1", "2.1.0rc1", "release-2.1.0", "2.1.0.1"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    StableVersion.parse(value)


class UpdatePolicyTest(unittest.TestCase):
    def test_newer_release_is_available(self):
        decision = evaluate_update("2.1.0", release("2.2.0"), now=1000)

        self.assertIs(decision.kind, UpdateDecisionKind.AVAILABLE)

    def test_ignored_version_is_suppressed_but_a_newer_one_is_not(self):
        ignored = evaluate_update(
            "2.1.0",
            release("2.2.0"),
            ignored_version="2.2.0",
            now=1000,
        )
        newer = evaluate_update(
            "2.1.0",
            release("2.3.0"),
            ignored_version="2.2.0",
            now=1000,
        )

        self.assertIs(ignored.kind, UpdateDecisionKind.IGNORED)
        self.assertIs(newer.kind, UpdateDecisionKind.AVAILABLE)

    def test_snooze_suppresses_only_until_its_deadline(self):
        snoozed = evaluate_update(
            "2.1.0",
            release("2.2.0"),
            snoozed_until=1001,
            now=1000,
        )
        expired = evaluate_update(
            "2.1.0",
            release("2.2.0"),
            snoozed_until=1000,
            now=1000,
        )

        self.assertIs(snoozed.kind, UpdateDecisionKind.SNOOZED)
        self.assertIs(expired.kind, UpdateDecisionKind.AVAILABLE)

    def test_current_or_older_release_is_up_to_date(self):
        for version in ("2.1.0", "2.0.0"):
            with self.subTest(version=version):
                decision = evaluate_update(
                    "2.1.0", release(version), now=1000
                )
                self.assertIs(decision.kind, UpdateDecisionKind.UP_TO_DATE)

    def test_automatic_checks_obey_the_enabled_flag_and_deadline(self):
        self.assertFalse(automatic_check_due(False, 0, now=1000))
        self.assertFalse(automatic_check_due(True, 1001, now=1000))
        self.assertTrue(automatic_check_due(True, 1000, now=1000))

    def test_failure_backoff_never_checks_more_than_daily(self):
        self.assertEqual(next_automatic_check_at(1000, 0), 87400)
        self.assertEqual(next_automatic_check_at(1000, 1), 173800)
        self.assertLessEqual(
            next_automatic_check_at(1000, 20),
            1000 + 7 * 24 * 60 * 60,
        )


if __name__ == "__main__":
    unittest.main()
