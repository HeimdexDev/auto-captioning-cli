"""Comparison-join tests: union of scene_ids, reference projection, null tolerance."""

from __future__ import annotations

from heimdex_ptp.comparison import build_comparison


def _gen(scene_id):
    return {
        "scene_id": scene_id,
        "keyframe_paths": ["a.jpg"],
        "references": [
            {
                "ref_id": "ref_a", "annotator_id": "claude_synthetic_a",
                "annotated_at": "2026-01-01T00:00:00Z",
                "caption": "사람 중심 캡션", "shot_type": "medium",
                "motion_type": "subject_motion", "temporal_change": "minor",
                "text_on_screen": None, "mood": ["casual"], "notes": "",
            }
        ],
    }


def test_union_of_scene_ids():
    human = {"v__scene_001": "사람 캡션", "v__scene_002": "사람 캡션2"}
    generated = {"v__scene_002": _gen("v__scene_002"), "v__scene_003": _gen("v__scene_003")}
    entries = build_comparison(human, generated)
    ids = [e["scene_id"] for e in entries]
    assert ids == ["v__scene_001", "v__scene_002", "v__scene_003"]


def test_video_id_derived_from_scene_id():
    entries = build_comparison({}, {"F_ws4NaorhA__scene_015": _gen("F_ws4NaorhA__scene_015")})
    assert entries[0]["video_id"] == "F_ws4NaorhA"


def test_reference_projection_drops_annotator_fields():
    entries = build_comparison({}, {"v__scene_001": _gen("v__scene_001")})
    ref = entries[0]["claude_references"][0]
    assert "annotator_id" not in ref
    assert "annotated_at" not in ref
    assert ref["ref_id"] == "ref_a"
    assert ref["caption"] == "사람 중심 캡션"
    assert ref["motion_type"] == "subject_motion"
    assert ref["temporal_change"] == "minor"
    assert "product_focus" not in ref


def test_missing_sides_yield_nulls():
    entries = build_comparison({"v__scene_001": "사람만 있음"}, {})
    e = entries[0]
    assert e["human_caption"] == "사람만 있음"
    assert e["claude_references"] == []
    assert e["video_url"] is None
    assert e["keyframes"] == []
    assert e["quality_notes"] == {
        "human_strength": "", "claude_strength": "", "claude_failure_modes": [],
    }
