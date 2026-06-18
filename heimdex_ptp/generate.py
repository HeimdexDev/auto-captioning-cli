"""Stage 3 — ``generate``: call Claude (vision) for 3 references per scene.

Per job we send ONE Messages-API request:
  * the skill + reference guides as a single CACHED system block (one cache
    write, then cheap reads for every subsequent scene),
  * the job's rendered prompt,
  * the scene's keyframes as base64 images,
  * constrained to the combined caption-eval schema via ``output_config.format``,
    passed through ``extra_body`` so it works on any anthropic SDK version.

We force ``scene_id`` and ``keyframe_paths`` from the job afterwards so the model
cannot drift those. Caption LENGTH (30–80) is NOT enforced here — structured
outputs strip string-length constraints — so always run ``validate`` after.

Cost guards: ``--dry-run`` (no API call), ``--limit N``, and skip scenes whose
output already exists (unless ``--overwrite``).
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from .config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    IMAGE_MEDIA_TYPES,
    load_env_files,
)

# Combined single-scene schema (SHAPE only — enums + required fields + 3 refs).
_REF_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "ref_id",
        "annotator_id",
        "annotated_at",
        "caption",
        "shot_type",
        "motion_type",
        "temporal_change",
        "text_on_screen",
        "mood",
        "notes",
    ],
    "properties": {
        "ref_id": {"type": "string", "enum": ["ref_a", "ref_b", "ref_c"]},
        "annotator_id": {"type": "string"},
        "annotated_at": {"type": "string"},
        "caption": {"type": "string"},
        "shot_type": {
            "type": "string",
            "enum": ["closeup", "medium", "full", "wide", "detail", "ots"],
        },
        "motion_type": {
            "type": "string",
            "enum": [
                "static",
                "subject_motion",
                "camera_motion",
                "object_motion",
                "scene_transition",
            ],
        },
        "temporal_change": {
            "type": "string",
            "enum": ["none", "minor", "major"],
        },
        "text_on_screen": {
            "anyOf": [
                {"type": "array", "items": {"type": "string"}},
                {"type": "null"},
            ]
        },
        "mood": {
            "anyOf": [
                {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "energetic",
                            "calm",
                            "luxurious",
                            "casual",
                            "warm",
                            "professional",
                        ],
                    },
                },
                {"type": "null"},
            ]
        },
        "notes": {"type": "string"},
    },
}

OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["scene_id", "keyframe_paths", "references"],
    "properties": {
        "scene_id": {"type": "string"},
        "keyframe_paths": {"type": "array", "items": {"type": "string"}},
        "references": {"type": "array", "items": _REF_SCHEMA},
    },
}


def _eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def _load_image_block(path_str: str) -> dict:
    p = Path(path_str)
    if not p.exists():
        raise FileNotFoundError(f"keyframe not found: {p}")
    media_type = IMAGE_MEDIA_TYPES.get(p.suffix.lower())
    if media_type is None:
        raise ValueError(f"unsupported image type: {p.suffix} ({p})")
    data = base64.standard_b64encode(p.read_bytes()).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


def _build_system_blocks(job: dict) -> list[dict]:
    """Skill + guides as ONE cached system block (stable across all scenes)."""
    parts: list[tuple[str, str]] = []
    skill_file = job.get("skill_file")
    if skill_file and Path(skill_file).exists():
        parts.append(("SKILL.md", Path(skill_file).read_text(encoding="utf-8")))
    for label, path_str in (job.get("guide_files") or {}).items():
        if path_str and Path(path_str).exists():
            parts.append((label, Path(path_str).read_text(encoding="utf-8")))

    if not parts:
        _eprint("  warning: no skill/guide files on disk; sending prompt only")
        return []

    header = (
        "You label live-commerce scenes for the Heimdex caption-eval dataset. "
        "The following is the skill and its reference guides. Follow them exactly "
        "and reuse the combined single-scene output format — do not invent a "
        "different schema.\n\n"
    )
    text = header + "\n\n".join(f"===== {label} =====\n{body}" for label, body in parts)
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _output_path(job: dict, out_dir: Path) -> Path:
    target = job.get("output_target")
    if target:
        return Path(target)
    return out_dir / f"{job['scene_id']}.json"


def caption_one(client, job: dict, model: str, max_tokens: int) -> dict:
    """Send one Messages request for a job and return the parsed combined object."""
    system = _build_system_blocks(job)
    content: list[dict] = [{"type": "text", "text": job["prompt"]}]
    for kf in job["keyframe_paths"]:
        content.append(_load_image_block(kf))

    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system or None,
        messages=[{"role": "user", "content": content}],
        extra_body={
            "output_config": {
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}
            }
        },
    )

    text = next((b.text for b in resp.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(
            f"no text block in response (stop_reason={resp.stop_reason})"
        )
    parsed = json.loads(text)

    # Force authoritative fields from the job — the model must not drift these.
    parsed["scene_id"] = job["scene_id"]
    parsed["keyframe_paths"] = job["keyframe_paths"]

    u = resp.usage
    _eprint(
        f"  tokens in={u.input_tokens} out={u.output_tokens} "
        f"cache_write={getattr(u, 'cache_creation_input_tokens', 0)} "
        f"cache_read={getattr(u, 'cache_read_input_tokens', 0)}"
    )
    return parsed


def run_generate(
    jobs: list[dict],
    out_dir: Path,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    limit: int | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
    env_dirs: list[Path] | None = None,
) -> int:
    """Caption every job. Returns a process-style exit code (0 ok, 1 on failures)."""
    if limit is not None:
        jobs = jobs[:limit]
    if not jobs:
        _eprint("no jobs to run")
        return 0

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = None
    if not dry_run:
        # Pick up ANTHROPIC_API_KEY from .env WITHOUT overriding the real env.
        candidates = [Path.cwd() / ".env"]
        for d in env_dirs or []:
            candidates.append(Path(d) / ".env")
        load_env_files(*candidates)
        import os

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit(
                "ERROR: ANTHROPIC_API_KEY is not set (checked the environment and "
                "a .env in the working dir / jobs dir)."
            )
        try:
            import anthropic
        except ImportError as e:
            raise SystemExit(
                "ERROR: the 'anthropic' package is required for live runs "
                "(pip install anthropic)."
            ) from e
        client = anthropic.Anthropic()

    written = skipped = failed = 0
    for job in jobs:
        scene_id = job.get("scene_id", "<unknown>")
        out = _output_path(job, out_dir)

        if out.exists() and not overwrite:
            _eprint(f"skip (exists): {scene_id} -> {out}")
            skipped += 1
            continue

        n_kf = len(job.get("keyframe_paths", []))
        if dry_run:
            print(f"[dry-run] would caption {scene_id} ({n_kf} keyframe(s)) -> {out}")
            continue

        _eprint(f"captioning {scene_id} ({n_kf} keyframe(s)) with {model} ...")
        try:
            result = caption_one(client, job, model, max_tokens)
        except Exception as e:  # noqa: BLE001 — keep the batch going
            _eprint(f"  FAILED {scene_id}: {type(e).__name__}: {e}")
            failed += 1
            continue

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _eprint(f"  wrote {out}")
        written += 1

    if dry_run:
        print(f"[dry-run] {len(jobs)} job(s); {skipped} already have output")
        return 0

    print(f"done: {written} written, {skipped} skipped, {failed} failed")
    return 1 if failed else 0
