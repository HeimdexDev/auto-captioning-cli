#!/usr/bin/env python3
"""
Heimdex Caption Eval output validator — spatiotemporal flow schema.

Usage:
    python validate_output.py <output.json>

Accepts either a single scene object or a multi-scene wrapper:
    { "scene_id": ..., "keyframe_paths": [...], "references": [...] }
or
    { "scenes": [ {...}, {...} ] }

Checks:
  - required top-level fields present
  - exactly 3 references, ref_id ∈ {ref_a, ref_b, ref_c}, no duplicates
  - each reference: required fields, caption length 30~80 Unicode chars,
    valid enums (shot_type, motion_type, temporal_change), nullable list lengths
  - text_on_screen and mood, when not null, are lists of 1~3 items
  - WARNING: caption diversity across 3 refs (Jaccard over content tokens)
  - WARNING: objective fields (shot_type / motion_type / temporal_change) differ
    across refs in the same scene (they describe the same scene, should align)
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

VALID_SHOT_TYPE = {"closeup", "medium", "full", "wide", "detail", "ots"}
VALID_MOTION_TYPE = {
    "static",
    "subject_motion",
    "camera_motion",
    "object_motion",
    "scene_transition",
}
VALID_TEMPORAL_CHANGE = {"none", "minor", "major"}
VALID_MOOD = {"energetic", "calm", "luxurious", "casual", "warm", "professional"}
EXPECTED_REF_IDS = ["ref_a", "ref_b", "ref_c"]

CAPTION_MIN = 30
CAPTION_MAX = 80

DIVERSITY_THRESHOLD = 0.85  # Jaccard above this => WARN
MIN_TOKEN_LEN = 2


def _tokenize_for_diversity(text: str) -> set[str]:
    cleaned = re.sub(r"[^\w가-힣]+", " ", text.lower())
    tokens = [t for t in cleaned.split() if len(t) >= MIN_TOKEN_LEN]
    return set(tokens)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = a & b
    union = a | b
    return len(inter) / len(union) if union else 0.0


def _check_nullable_list(ref: dict, field: str, loc: str, errors: list[str]) -> None:
    val = ref.get(field, None)
    if val is None:
        return
    if not isinstance(val, list):
        errors.append(f"{loc}.{field}: must be a list or null")
        return
    if not (1 <= len(val) <= 3):
        errors.append(
            f"{loc}.{field}: length {len(val)} not in [1, 3]; use null if not applicable"
        )
    for k, item in enumerate(val):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{loc}.{field}[{k}]: must be a non-empty string")


def validate_reference(ref: dict, loc: str) -> list[str]:
    errors: list[str] = []

    required = (
        "ref_id",
        "annotator_id",
        "annotated_at",
        "caption",
        "shot_type",
        "motion_type",
        "temporal_change",
    )
    for field in required:
        if field not in ref:
            errors.append(f"{loc}: missing required field '{field}'")

    # caption length (Unicode char count)
    caption = ref.get("caption")
    if isinstance(caption, str):
        n = len(caption)
        if n < CAPTION_MIN or n > CAPTION_MAX:
            errors.append(
                f"{loc}.caption: length {n} not in [{CAPTION_MIN}, {CAPTION_MAX}] "
                f"(Unicode chars). Caption: {caption!r}"
            )
    elif "caption" in ref:
        errors.append(f"{loc}.caption: must be a string")

    # enums
    st = ref.get("shot_type")
    if st is not None and st not in VALID_SHOT_TYPE:
        errors.append(f"{loc}.shot_type: '{st}' not in {sorted(VALID_SHOT_TYPE)}")

    mt = ref.get("motion_type")
    if mt is not None and mt not in VALID_MOTION_TYPE:
        errors.append(f"{loc}.motion_type: '{mt}' not in {sorted(VALID_MOTION_TYPE)}")

    tc = ref.get("temporal_change")
    if tc is not None and tc not in VALID_TEMPORAL_CHANGE:
        errors.append(
            f"{loc}.temporal_change: '{tc}' not in {sorted(VALID_TEMPORAL_CHANGE)}"
        )

    # nullable lists
    _check_nullable_list(ref, "text_on_screen", loc, errors)

    mood = ref.get("mood", None)
    if mood is not None:
        if not isinstance(mood, list):
            errors.append(f"{loc}.mood: must be a list or null")
        else:
            if not (1 <= len(mood) <= 3):
                errors.append(
                    f"{loc}.mood: length {len(mood)} not in [1, 3]; use null if uncertain"
                )
            seen = set()
            for k, item in enumerate(mood):
                if item not in VALID_MOOD:
                    errors.append(f"{loc}.mood[{k}]: '{item}' not in {sorted(VALID_MOOD)}")
                if item in seen:
                    errors.append(f"{loc}.mood[{k}]: duplicate value '{item}'")
                seen.add(item)

    return errors


def validate_scene(scene: dict, loc: str = "scene") -> list[str]:
    errors: list[str] = []

    for field in ("scene_id", "keyframe_paths", "references"):
        if field not in scene:
            errors.append(f"{loc}: missing required field '{field}'")

    kfs = scene.get("keyframe_paths", [])
    if not isinstance(kfs, list) or not kfs:
        errors.append(f"{loc}.keyframe_paths: must be a non-empty list of strings")
    else:
        for k, p in enumerate(kfs):
            if not isinstance(p, str) or not p.strip():
                errors.append(f"{loc}.keyframe_paths[{k}]: must be a non-empty string")

    refs = scene.get("references", [])
    if not isinstance(refs, list):
        errors.append(f"{loc}.references: must be a list")
        return errors

    if len(refs) != 3:
        errors.append(f"{loc}.references: must have exactly 3 entries (got {len(refs)})")

    seen_ref_ids: list[str] = []
    for i, ref in enumerate(refs):
        rloc = f"{loc}.references[{i}]"
        if not isinstance(ref, dict):
            errors.append(f"{rloc}: must be an object")
            continue
        errors.extend(validate_reference(ref, rloc))
        rid = ref.get("ref_id")
        if rid:
            if rid in seen_ref_ids:
                errors.append(f"{rloc}: duplicate ref_id '{rid}'")
            seen_ref_ids.append(rid)

    if len(refs) == 3 and len(seen_ref_ids) == 3:
        if sorted(seen_ref_ids) != sorted(EXPECTED_REF_IDS):
            errors.append(
                f"{loc}.references: ref_ids must be exactly {EXPECTED_REF_IDS}; "
                f"got {seen_ref_ids}"
            )

    # Cross-ref coherence (warnings)
    if len(refs) == 3 and all(isinstance(r, dict) for r in refs):
        for field in ("shot_type", "motion_type", "temporal_change"):
            vals = {r.get(field) for r in refs if r.get(field)}
            if len(vals) > 1:
                errors.append(
                    f"WARNING {loc}.references: {field} differs across refs "
                    f"({sorted(vals)}); objective field should align"
                )

        captions = [r.get("caption", "") for r in refs]
        token_sets = [_tokenize_for_diversity(c) for c in captions if isinstance(c, str)]
        if len(token_sets) == 3:
            for a, b in [(0, 1), (0, 2), (1, 2)]:
                sim = _jaccard(token_sets[a], token_sets[b])
                if sim > DIVERSITY_THRESHOLD:
                    errors.append(
                        f"WARNING {loc}.references: caption pair ({a},{b}) Jaccard={sim:.2f} "
                        f"> {DIVERSITY_THRESHOLD} — refs too similar, vary the temporal lens "
                        "(행동/공간·시점/요약)"
                    )

    return errors


def validate(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["root: must be a JSON object"]

    if "scenes" in data and isinstance(data["scenes"], list):
        errors: list[str] = []
        if not data["scenes"]:
            errors.append("root.scenes: must contain at least one scene")
        for idx, scene in enumerate(data["scenes"]):
            if not isinstance(scene, dict):
                errors.append(f"scenes[{idx}]: must be an object")
                continue
            errors.extend(validate_scene(scene, loc=f"scenes[{idx}]"))
        return errors

    return validate_scene(data, loc="scene")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Path to output JSON")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"ERROR: file not found: {args.path}", file=sys.stderr)
        return 2

    try:
        data = json.loads(args.path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON: {e}", file=sys.stderr)
        return 2

    issues = validate(data)
    real_errors = [e for e in issues if not e.startswith("WARNING")]
    warnings = [e for e in issues if e.startswith("WARNING")]

    if not issues:
        n_scenes = len(data.get("scenes", [data]))
        print(f"✓ PASS — {n_scenes} scene(s) validated")
        return 0

    status = "✗ FAIL" if real_errors else "⚠ WARN"
    print(f"{status} — {len(real_errors)} error(s), {len(warnings)} warning(s)")
    for e in issues:
        print(f"  {e}")
    return 1 if real_errors else 0


if __name__ == "__main__":
    sys.exit(main())
