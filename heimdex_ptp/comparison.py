"""Stage 5 — ``build-comparison``: join human captions with Claude output.

Reads a human-caption JSONL (each row ``{"scene_id", "human_caption"}``) and the
per-scene generated combined-schema files, then emits an array of viewer
entries over the UNION of scene_ids. Media URLs are left null/empty here —
``resolve-media`` fills them in later.

Each Claude reference is projected to the viewer's ``claude_references`` shape
(the display fields only; annotator_id/annotated_at are dropped).
"""

from __future__ import annotations

import json
from pathlib import Path

# Display fields the viewer reads from each reference.
_REF_DISPLAY_FIELDS = (
    "ref_id",
    "caption",
    "shot_type",
    "motion_type",
    "temporal_change",
    "text_on_screen",
    "mood",
    "notes",
)


def _video_id_of(scene_id: str) -> str:
    return scene_id.split("__", 1)[0]


def load_human_captions(path: Path) -> dict[str, str]:
    """Map scene_id -> human_caption from a JSONL file (missing file -> empty)."""
    path = Path(path)
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        sid = row.get("scene_id")
        if sid:
            out[sid] = row.get("human_caption")
    return out


def load_generated(generated_dir: Path) -> dict[str, dict]:
    """Map scene_id -> parsed combined-schema object from data/generated/*.json."""
    generated_dir = Path(generated_dir)
    out: dict[str, dict] = {}
    if not generated_dir.exists():
        return out
    for f in sorted(generated_dir.glob("*.json")):
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        sid = obj.get("scene_id") or f.stem
        out[sid] = obj
    return out


def _project_references(obj: dict | None) -> list[dict]:
    if not obj:
        return []
    refs = obj.get("references") or []
    projected = []
    for ref in refs:
        projected.append({k: ref.get(k) for k in _REF_DISPLAY_FIELDS})
    return projected


def build_comparison(
    human: dict[str, str], generated: dict[str, dict]
) -> list[dict]:
    """Join human + generated into viewer entries over the union of scene_ids."""
    scene_ids = sorted(set(human) | set(generated))
    entries: list[dict] = []
    for sid in scene_ids:
        gen = generated.get(sid)
        entries.append(
            {
                "scene_id": sid,
                "video_id": _video_id_of(sid),
                "video_url": None,
                "full_video_url": None,
                "clip_start": None,
                "clip_end": None,
                "keyframes": [],
                "subtitle_url": None,
                "human_caption": human.get(sid),
                "claude_references": _project_references(gen),
                "quality_notes": {
                    "human_strength": "",
                    "claude_strength": "",
                    "claude_failure_modes": [],
                },
            }
        )
    return entries


def write_comparison(entries: list[dict], path: Path, pretty: bool = True) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    indent = 2 if pretty else None
    path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )
