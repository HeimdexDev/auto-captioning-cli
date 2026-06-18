"""Curation: determinism, scene count, and minimal unique-video selection."""

from __future__ import annotations

from heimdex_ptp.curate import curate
from heimdex_ptp.scenes import Scene


def _make(video, n_scenes, category, kf=2):
    return [
        Scene(scene_id=f"{video}__scene_{i:03d}", video_id=video, scene_num=i,
              keyframe_paths=tuple(f"{video}_{i}_{k}.jpg" for k in range(kf)))
        for i in range(n_scenes)
    ]


def _corpus():
    scenes, meta = [], {}
    spec = [("vidA", 15, "beauty"), ("vidB", 14, "vlog"), ("vidC", 12, "food"),
            ("vidD", 9, "edu"), ("vidE", 8, "game"), ("vidF", 5, "tech")]
    for v, n, c in spec:
        ss = _make(v, n, c)
        scenes += ss
        for s in ss:
            meta[s.scene_id] = {"category": c, "channel": v}
    return scenes, meta


def test_curate_deterministic():
    scenes, meta = _corpus()
    assert curate(scenes, meta, n=25, per_video=5) == curate(scenes, meta, n=25, per_video=5)


def test_curate_count_and_min_videos():
    scenes, meta = _corpus()
    ids = curate(scenes, meta, n=25, per_video=5)
    assert len(ids) == 25
    vids = {i.split("__")[0] for i in ids}
    # 25 scenes at 5/video -> exactly 5 unique videos (minimal downloads)
    assert len(vids) == 5


def test_curate_prefers_distinct_categories():
    scenes, meta = _corpus()
    ids = curate(scenes, meta, n=25, per_video=5)
    cats = {meta[i]["category"] for i in ids}
    assert len(cats) == 5  # one category per chosen video


def test_curate_respects_per_video_cap():
    scenes, meta = _corpus()
    ids = curate(scenes, meta, n=10, per_video=2)
    from collections import Counter
    per = Counter(i.split("__")[0] for i in ids)
    assert all(c <= 2 for c in per.values())
