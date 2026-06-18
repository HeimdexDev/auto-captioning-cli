"""Frame-sampling tests: adaptive count + even spacing (pure, no ffmpeg)."""

from __future__ import annotations

from heimdex_ptp.frames import even_timestamps, frame_count_for_duration


def test_adaptive_count_clamped_low():
    # 3s clip: round(3/2.5)=1 -> clamped up to the floor of 4
    assert frame_count_for_duration(3.0) == 4
    assert frame_count_for_duration(0.0) == 4


def test_adaptive_count_midrange():
    assert frame_count_for_duration(20.0) == 8   # round(8.0)
    assert frame_count_for_duration(19.3) == 8   # round(7.72)
    assert frame_count_for_duration(12.5) == 5   # round(5.0)


def test_adaptive_count_clamped_high():
    assert frame_count_for_duration(60.0) == 12  # round(24) -> capped at 12
    assert frame_count_for_duration(300.0) == 12


def test_custom_budget():
    assert frame_count_for_duration(20.0, secs_per_frame=5.0, lo=2, hi=6) == 4
    assert frame_count_for_duration(100.0, secs_per_frame=5.0, lo=2, hi=6) == 6


def test_even_timestamps_endpoints_included():
    ts = even_timestamps(20.0, 8)
    assert len(ts) == 8
    assert ts[0] == 0.0
    assert ts[-1] == 20.0
    # strictly increasing
    assert all(ts[i] < ts[i + 1] for i in range(len(ts) - 1))


def test_even_timestamps_single():
    assert even_timestamps(10.0, 1) == [0.0]
