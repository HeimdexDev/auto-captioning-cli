"""Job-building tests: prompt determinism, temporal contract, output shape."""

from __future__ import annotations

from pathlib import Path

from heimdex_ptp.jobs import build_job, build_jobs, render_prompt
from heimdex_ptp.scenes import Scene


def _scene(n=2):
    paths = tuple(
        f"/abs/Dz57B0QkaCU_scene_024_frame_0{i}.jpg" for i in range(n)
    )
    return Scene(
        scene_id="Dz57B0QkaCU__scene_024",
        video_id="Dz57B0QkaCU",
        scene_num=24,
        keyframe_paths=paths,
    )


def test_prompt_is_deterministic():
    s = _scene()
    assert render_prompt(s) == render_prompt(s)


def test_prompt_is_spatiotemporal_not_product():
    p = render_prompt(_scene())
    assert "SPATIOTEMPORAL FLOW" in p
    assert "NOT to extract product details" in p
    # the 3 temporal lenses
    assert "ref_a: action/event flow" in p
    assert "ref_b: spatial & viewpoint change" in p
    assert "ref_c: whole-scene narrative arc" in p


def test_prompt_marks_chronological_order():
    p = render_prompt(_scene(n=3))
    assert "CHRONOLOGICAL ORDER" in p
    assert "(earliest)" in p
    assert "(latest)" in p
    # basenames listed, not absolute paths
    assert "Dz57B0QkaCU_scene_024_frame_00.jpg" in p
    assert "/abs/" not in p


def test_single_frame_has_no_order_tags():
    p = render_prompt(_scene(n=1))
    assert "(earliest)" not in p
    assert "(latest)" not in p


def test_prompt_temporal_grounding_rule_present():
    p = render_prompt(_scene())
    assert "Describe ONLY changes visible BETWEEN the given frames" in p
    assert "near-identical" in p
    assert 'temporal_change to "none"' in p


def test_prompt_lists_temporal_meta_enums():
    p = render_prompt(_scene())
    assert "EXACTLY 3" in p
    assert "30-80 Unicode characters" in p
    assert "Do NOT invent a different schema" in p
    for v in ("static", "subject_motion", "camera_motion", "object_motion", "scene_transition"):
        assert v in p
    for v in ("none", "minor", "major"):
        assert v in p
    for shot in ("closeup", "medium", "full", "wide", "detail", "ots"):
        assert shot in p
    # commerce fields must be gone
    assert "product_focus" not in p
    assert "host_action" not in p


def test_build_job_shape():
    job = build_job(_scene(), Path("/skill"), Path("data/generated"))
    assert job["scene_id"] == "Dz57B0QkaCU__scene_024"
    assert job["keyframe_paths"] == list(_scene().keyframe_paths)
    assert job["skill_file"].endswith("SKILL.md")
    assert set(job["guide_files"]) == {
        "caption_writing_principles", "meta_fields",
        "output_schema", "examples", "output_template",
    }
    assert job["output_target"].endswith("Dz57B0QkaCU__scene_024.json")
    assert "prompt" in job and job["prompt"]


def test_build_jobs_limit(tmp_path):
    for i in range(3):
        (tmp_path / f"vid_scene_00{i}_frame_00.jpg").write_bytes(b"\xff\xd8\xff")
    jobs = build_jobs(tmp_path, Path("/skill"), Path("data/generated"), limit=2)
    assert len(jobs) == 2
