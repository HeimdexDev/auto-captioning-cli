"""Stage 2 — ``build-jobs``: one Claude captioning job per scene.

Each job is a JSON object with the scene id, absolute keyframe paths, the skill
file paths (sent as a cached system block at generate time), an output target,
and a fully-rendered ``prompt`` that instructs Claude to follow the caption-eval
skill and describe the COMBINED single-scene schema (ref_a/ref_b/ref_c).

The captions describe the scene's SPATIOTEMPORAL FLOW — what happens, moves, and
changes across the chronologically-ordered keyframes — not product details.

The prompt is rendered deterministically — the same scene always produces the
same prompt string — so the build is reproducible and unit-testable.
"""

from __future__ import annotations

import json
from pathlib import Path

from .scenes import Scene, group_keyframes

# Reference guide files inside the skill dir, by logical label.
GUIDE_FILES = {
    "caption_writing_principles": "references/caption_writing_principles.md",
    "meta_fields": "references/meta_fields.md",
    "output_schema": "references/output_schema.md",
    "examples": "references/examples.md",
    "output_template": "assets/output_template.json",
}

_PROMPT_TEMPLATE = """\
You are labeling ONE live-commerce scene for the Heimdex caption-eval dataset.
Your job is to describe the SPATIOTEMPORAL FLOW of the scene — what happens,
moves, and changes ACROSS the keyframes — NOT to extract product details.
Follow the Heimdex caption-eval skill and reference guides exactly (SKILL.md,
caption_writing_principles.md, meta_fields.md, output_schema.md, examples.md).
Do NOT invent a different schema — reuse the combined single-scene format.

Scene id: {scene_id}
Keyframes ({n_kf} image(s), in CHRONOLOGICAL ORDER — earliest first, latest last;
the images are given to you in this same order):
{keyframe_list}

How to read the frames:
- Compare the frames in order and describe what changes from the first to the last.
- The frames are sparse ordered SAMPLES of one scene, not continuous video.

Rules:
- Describe ONLY changes visible BETWEEN the given frames. Do NOT invent motion or
  intermediate actions not evidenced by the frames (e.g. don't say someone "walks
  across the room" from two frames — the path between them is unknown).
- If the frames are near-identical (or there is only one), say so and describe the
  spatial composition instead; set temporal_change to "none".
- Use ONLY visible information. No audio, no external knowledge, no evaluative
  adjectives. Do NOT infer brand, price, or product name (if visible on screen it
  belongs in text_on_screen, not the caption).
- Return ONLY valid JSON. No markdown, no commentary, no code fences.

Output: a single JSON object for this scene with a "references" array of EXACTLY 3
references, each from a different TEMPORAL LENS, in order:
- ref_a: action/event flow — what the subject(s) do across the frames, in order
  (annotator_id "claude_synthetic_a")
- ref_b: spatial & viewpoint change — how positions, framing, and the camera move
  across the frames (annotator_id "claude_synthetic_b")
- ref_c: whole-scene narrative arc — one sentence summarizing start -> end
  (annotator_id "claude_synthetic_c")

Each caption must be Korean, 30-80 Unicode characters, and the 3 captions must
differ in which temporal aspect they emphasize (not just word order).

Each reference requires these fields:
- caption (string, Korean, 30-80 chars)
- shot_type: one of closeup | medium | full | wide | detail | ots
- motion_type: one of static | subject_motion | camera_motion | object_motion |
  scene_transition (the dominant motion across the frames)
- temporal_change: one of none | minor | major (how much changes across the frames)
- text_on_screen: list of 1-3 visible strings, or null
- mood: list of 1-3 of energetic | calm | luxurious | casual | warm | professional,
  or null (use null when uncertain)
- notes: string (usually "")
- ref_id, annotator_id, annotated_at (ISO 8601 UTC)

Objective metadata (shot_type, motion_type, temporal_change) should stay essentially
consistent across the 3 references — they describe the same scene. Only mood may vary.

JSON shape:
{{
  "scene_id": "{scene_id}",
  "keyframe_paths": [...],
  "references": [ {{ "ref_id": "ref_a", ... }}, {{ "ref_id": "ref_b", ... }}, {{ "ref_id": "ref_c", ... }} ]
}}
"""


def render_prompt(scene: Scene) -> str:
    """Render the deterministic captioning prompt for a scene.

    Keyframes are listed by basename in chronological order, with the earliest
    and latest frames marked so the temporal direction is explicit.
    """
    n = len(scene.keyframe_paths)
    lines = []
    for i, p in enumerate(scene.keyframe_paths, 1):
        tag = ""
        if n > 1 and i == 1:
            tag = "   (earliest)"
        elif n > 1 and i == n:
            tag = "   (latest)"
        lines.append(f"  {i}. {Path(p).name}{tag}")
    keyframe_list = "\n".join(lines)
    return _PROMPT_TEMPLATE.format(
        scene_id=scene.scene_id,
        n_kf=n,
        keyframe_list=keyframe_list,
    )


def build_job(scene: Scene, skill_dir: Path, out_dir: Path) -> dict:
    """Assemble the JSONL job payload for one scene."""
    skill_dir = Path(skill_dir)
    guide_files = {
        label: str((skill_dir / rel).resolve()) for label, rel in GUIDE_FILES.items()
    }
    return {
        "scene_id": scene.scene_id,
        "video_id": scene.video_id,
        "keyframe_paths": list(scene.keyframe_paths),
        "skill_dir": str(skill_dir.resolve()),
        "skill_file": str((skill_dir / "SKILL.md").resolve()),
        "guide_files": guide_files,
        "output_target": str((Path(out_dir) / f"{scene.scene_id}.json")),
        "prompt": render_prompt(scene),
    }


def build_jobs(
    keyframes_dir: Path,
    skill_dir: Path,
    out_dir: Path,
    limit: int | None = None,
    frames_map: dict | None = None,
) -> list[dict]:
    """Group keyframes and build one job per scene.

    When ``frames_map`` (from ``extract-frames``) has entries for a scene, its
    extracted clip-spanning frames REPLACE the sparse dataset keyframes as the
    captioning input, so captions reflect the whole clip.
    """
    import dataclasses

    scenes = group_keyframes(keyframes_dir)
    if limit is not None:
        scenes = scenes[:limit]
    jobs = []
    for scene in scenes:
        entry = (frames_map or {}).get(scene.scene_id)
        if entry and entry.get("frames"):
            paths = tuple(f["path"] for f in entry["frames"])
            scene = dataclasses.replace(scene, keyframe_paths=paths)
        jobs.append(build_job(scene, skill_dir, out_dir))
    return jobs


def write_jobs(jobs: list[dict], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for job in jobs:
            fh.write(json.dumps(job, ensure_ascii=False) + "\n")


def read_jobs(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"jobs file not found: {path}")
    jobs = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            jobs.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON on line {i} of {path}: {e}") from e
    return jobs
