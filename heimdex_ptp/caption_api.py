"""Live captioning helper for the web server's POST /api/caption endpoint.

Given a scene's frame images (bytes), build the SAME request the offline `generate`
stage uses — the vendored skill as a cached system block + the temporal prompt +
the structured-output schema — call Claude, and return the 3 references projected
to the viewer's display fields. Single source of truth: reuses OUTPUT_SCHEMA,
render_prompt, the skill-block builder, and the display projection.

`anthropic` is imported lazily so this module stays import-safe (stdlib only) for
the zero-install static server; the import only happens when a caption is requested.
"""

from __future__ import annotations

import base64
import json

from .comparison import _REF_DISPLAY_FIELDS
from .config import DEFAULT_MAX_TOKENS, DEFAULT_MODEL, DEFAULT_SKILL_DIR
from .generate import OUTPUT_SCHEMA, _build_system_blocks
from .jobs import GUIDE_FILES, render_prompt
from .scenes import Scene


def _skill_job(skill_dir) -> dict:
    from pathlib import Path
    skill_dir = Path(skill_dir)
    return {
        "skill_file": str((skill_dir / "SKILL.md").resolve()),
        "guide_files": {
            label: str((skill_dir / rel).resolve()) for label, rel in GUIDE_FILES.items()
        },
    }


def caption_from_images(
    scene_id: str,
    images: list[bytes],
    *,
    skill_dir=DEFAULT_SKILL_DIR,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    media_type: str = "image/jpeg",
) -> dict:
    """Generate the 3 temporal references for a scene from its frame images.

    Returns ``{"scene_id", "claude_references": [...display-projected...]}``.
    """
    import anthropic

    video_id = scene_id.split("__", 1)[0]
    frame_names = tuple(f"{i:02d}.jpg" for i in range(len(images)))
    scene = Scene(scene_id=scene_id, video_id=video_id, scene_num=0,
                  keyframe_paths=frame_names)

    system = _build_system_blocks(_skill_job(skill_dir))
    content: list[dict] = [{"type": "text", "text": render_prompt(scene)}]
    for raw in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(raw).decode("utf-8"),
            },
        })

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from env
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system or None,
        messages=[{"role": "user", "content": content}],
        extra_body={"output_config": {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}}},
    )
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(f"no text block (stop_reason={resp.stop_reason})")
    parsed = json.loads(text)

    refs = [
        {k: r.get(k) for k in _REF_DISPLAY_FIELDS}
        for r in (parsed.get("references") or [])
    ]
    return {"scene_id": scene_id, "claude_references": refs}
