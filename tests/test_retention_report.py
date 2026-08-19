from datetime import datetime, timedelta, timezone

from scripts.retention_report import classify_retention

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def test_too_early_to_tell():
    cohort_start = NOW - timedelta(days=3)
    assert classify_retention(cohort_start, None, NOW, weeks=1) == "рано"


def test_no_activity_after_window_is_churned():
    cohort_start = NOW - timedelta(weeks=2)
    assert classify_retention(cohort_start, None, NOW, weeks=1) == "нет"


def test_activity_within_first_week_does_not_count_as_week_1_retention():
    cohort_start = NOW - timedelta(weeks=2)
    last_active = cohort_start + timedelta(days=2)
    assert classify_retention(cohort_start, last_active, NOW, weeks=1) == "нет"


def test_activity_after_threshold_counts_as_retained():
    cohort_start = NOW - timedelta(weeks=2)
    last_active = cohort_start + timedelta(days=10)
    assert classify_retention(cohort_start, last_active, NOW, weeks=1) == "да"
