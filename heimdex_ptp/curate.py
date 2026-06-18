"""Stage — ``curate``: auto-select a diverse subset of scenes for the try-it gallery.

Picks ~N scenes while MINIMIZING the number of unique source videos (each unique
video costs one full download during make-clips). Strategy: choose the fewest
high-scene-count videos that cover distinct categories, then round-robin scenes
from them (preferring scenes with more keyframes). Fully deterministic.

Emits a scene-list JSON (`[{"scene_id": ...}, ...]`) that make-clips reads via
``--comparison``.
"""

from __future__ import annotations

import json
from pathlib import Path

from .scenes import group_keyframes


def load_scene_meta(scenes_jsonl: Path) -> dict[str, dict]:
    meta: dict[str, dict] = {}
    for line in Path(scenes_jsonl).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        sid = r.get("scene_id")
        if sid:
            meta[sid] = {"category": r.get("category"), "channel": r.get("channel")}
    return meta


def curate(scenes, meta: dict[str, dict], n: int = 25, per_video: int = 5) -> list[str]:
    """Return up to ``n`` scene_ids spread across the fewest, most-diverse videos."""
    by_vid: dict[str, list] = {}
    for s in scenes:
        if s.scene_id in meta:  # must be in scenes.jsonl (needs keyframe_urls/video)
            by_vid.setdefault(s.video_id, []).append(s)

    videos_sorted = sorted(by_vid, key=lambda v: (-len(by_vid[v]), v))

    # greedily pick distinct-category videos until they can supply n scenes
    chosen: list[str] = []
    cats: set = set()
    for v in videos_sorted:
        c = meta[by_vid[v][0].scene_id]["category"]
        if c in cats:
            continue
        chosen.append(v)
        cats.add(c)
        if len(chosen) * per_video >= n:
            break
    # fall back to filling by count if distinct categories ran out
    if len(chosen) * per_video < n:
        for v in videos_sorted:
            if v not in chosen:
                chosen.append(v)
                if len(chosen) * per_video >= n:
                    break

    pools = {
        v: sorted(by_vid[v], key=lambda s: (-len(s.keyframe_paths), s.scene_num))[:per_video]
        for v in chosen
    }
    out: list[str] = []
    i = 0
    while len(out) < n and any(pools.values()):
        v = chosen[i % len(chosen)]
        if pools[v]:
            out.append(pools[v].pop(0).scene_id)
        i += 1
        if i > len(chosen) * (per_video + 1):
            break
    return out[:n]


def curate_to_file(
    keyframes_dir: Path, scenes_jsonl: Path, out: Path, n: int = 25, per_video: int = 5
) -> list[str]:
    scenes = group_keyframes(keyframes_dir)
    meta = load_scene_meta(scenes_jsonl)
    ids = curate(scenes, meta, n=n, per_video=per_video)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps([{"scene_id": s} for s in ids], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return ids
