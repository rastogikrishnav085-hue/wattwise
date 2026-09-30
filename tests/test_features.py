import numpy as np
import pandas as pd

from src.features import build_features, compute_shift_flags, FEATURE_COLUMNS


def test_build_features_has_no_nulls(demo_df):
    feat_df = build_features(demo_df)
    assert not feat_df[FEATURE_COLUMNS].isnull().any().any()


def test_build_features_drops_rows_for_lag_warmup(demo_df):
    feat_df = build_features(demo_df)
    # at least 168 rows (1 week) should be dropped for the longest lag
    assert len(feat_df) <= len(demo_df) - 168


def test_hour_feature_is_within_valid_range(demo_df):
    feat_df = build_features(demo_df)
    assert feat_df["hour"].between(0, 23).all()


def test_is_weekend_matches_day_of_week(demo_df):
    feat_df = build_features(demo_df)
    expected = feat_df["day_of_week"].isin([5, 6]).astype(int)
    assert (feat_df["is_weekend"] == expected).all()


# --- Shift-flag tests ---

def test_compute_shift_flags_marks_single_day_shift_active():
    hours = pd.Series(range(24))
    active, boundary = compute_shift_flags(hours, [("09:00", "17:00")])
    assert list(active) == [1 if 9 <= h < 17 else 0 for h in range(24)]


def test_compute_shift_flags_handles_overnight_shift():
    hours = pd.Series(range(24))
    active, _ = compute_shift_flags(hours, [("22:00", "06:00")])
    expected = [1 if (h >= 22 or h < 6) else 0 for h in range(24)]
    assert list(active) == expected


def test_compute_shift_flags_marks_boundary_at_start_and_end():
    hours = pd.Series(range(24))
    _, boundary = compute_shift_flags(hours, [("09:00", "17:00")])
    # boundary should be flagged at 9, 10 (start + 1) and 17, 18 (end + 1)
    for h in (9, 10, 17, 18):
        assert boundary.iloc[h] == 1
    for h in (3, 13, 20):
        assert boundary.iloc[h] == 0


def test_compute_shift_flags_supports_multiple_shifts():
    hours = pd.Series(range(24))
    active, _ = compute_shift_flags(hours, [("06:00", "14:00"), ("14:00", "22:00")])
    expected = [1 if 6 <= h < 22 else 0 for h in range(24)]
    assert list(active) == expected


def test_build_features_defaults_shift_pattern_when_none_given(demo_df):
    """No shift_pattern given should behave like the old fixed 9-17 window,
    so an unconfigured company doesn't silently get zeroed-out shift features."""
    feat_df = build_features(demo_df)
    assert feat_df["shift_active_flag"].sum() > 0
    assert feat_df["shift_active_flag"].isin([0, 1]).all()


def test_build_features_respects_custom_shift_pattern(demo_df):
    """Two 8-hour windows can have the same TOTAL active-hour count by
    coincidence (9-17 and 00:00-08:00 are both 8 hours) — the real test is
    that the pattern actually moved to different hours, not the count."""
    default_feat = build_features(demo_df)
    custom_feat = build_features(demo_df, shift_pattern=[("00:00", "08:00")])

    midnight_rows = default_feat["hour"] == 0
    noon_rows = default_feat["hour"] == 12

    # hour 0 should be active under the custom (midnight) pattern but not the default
    assert custom_feat.loc[midnight_rows, "shift_active_flag"].eq(1).all()
    assert default_feat.loc[midnight_rows, "shift_active_flag"].eq(0).all()

    # hour 12 should be active under the default (9-17) pattern but not the custom one
    assert default_feat.loc[noon_rows, "shift_active_flag"].eq(1).all()
    assert custom_feat.loc[noon_rows, "shift_active_flag"].eq(0).all()
