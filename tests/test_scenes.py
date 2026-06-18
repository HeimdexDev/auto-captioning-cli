"""Scene-grouping tests: filename parsing, scene_id format, deterministic order."""

from __future__ import annotations

from pathlib import Path

import pytest

from heimdex_ptp.scenes import group_keyframes


def _touch(d: Path, name: str) -> None:
    (d / name).write_bytes(b"\xff\xd8\xff\xe0jpeg")  # tiny non-empty file


def test_groups_frames_into_scenes(tmp_path):
    _touch(tmp_path, "Dz57B0QkaCU_scene_024_frame_00.jpg")
    _touch(tmp_path, "Dz57B0QkaCU_scene_024_frame_01.jpg")
    _touch(tmp_path, "Dz57B0QkaCU_scene_025_frame_00.jpg")

    scenes = group_keyframes(tmp_path)
    assert len(scenes) == 2
    s0, s1 = scenes
    assert s0.scene_id == "Dz57B0QkaCU__scene_024"  # DOUBLE underscore
    assert s0.video_id == "Dz57B0QkaCU"
    assert len(s0.keyframe_paths) == 2
    assert s1.scene_id == "Dz57B0QkaCU__scene_025"
    assert len(s1.keyframe_paths) == 1


def test_video_id_may_contain_underscore(tmp_path):
    _touch(tmp_path, "F_ws4NaorhA_scene_015_frame_00.jpg")
    scenes = group_keyframes(tmp_path)
    assert len(scenes) == 1
    assert scenes[0].video_id == "F_ws4NaorhA"
    assert scenes[0].scene_id == "F_ws4NaorhA__scene_015"


def test_frames_sorted_within_scene(tmp_path):
    _touch(tmp_path, "vid_scene_001_frame_02.jpg")
    _touch(tmp_path, "vid_scene_001_frame_00.jpg")
    _touch(tmp_path, "vid_scene_001_frame_01.jpg")
    scenes = group_keyframes(tmp_path)
    names = [Path(p).name for p in scenes[0].keyframe_paths]
    assert names == [
        "vid_scene_001_frame_00.jpg",
        "vid_scene_001_frame_01.jpg",
        "vid_scene_001_frame_02.jpg",
    ]


def test_deterministic_order_across_videos(tmp_path):
    _touch(tmp_path, "bbb_scene_001_frame_00.jpg")
    _touch(tmp_path, "aaa_scene_002_frame_00.jpg")
    _touch(tmp_path, "aaa_scene_001_frame_00.jpg")
    scenes = group_keyframes(tmp_path)
    ids = [s.scene_id for s in scenes]
    assert ids == ["aaa__scene_001", "aaa__scene_002", "bbb__scene_001"]


def test_grouping_is_stable_repeated(tmp_path):
    for n in ("x_scene_003_frame_00.jpg", "x_scene_001_frame_00.jpg", "x_scene_002_frame_00.jpg"):
        _touch(tmp_path, n)
    a = [s.scene_id for s in group_keyframes(tmp_path)]
    b = [s.scene_id for s in group_keyframes(tmp_path)]
    assert a == b == ["x__scene_001", "x__scene_002", "x__scene_003"]


def test_skill_format_sc_kf(tmp_path):
    _touch(tmp_path, "live_001__sc_042__kf_01.jpg")
    _touch(tmp_path, "live_001__sc_042__kf_02.jpg")
    scenes = group_keyframes(tmp_path)
    assert len(scenes) == 1
    assert scenes[0].scene_id == "live_001__sc_042"
    assert len(scenes[0].keyframe_paths) == 2


def test_fallback_id_is_deterministic(tmp_path):
    _touch(tmp_path, "random_thing.jpg")
    a = group_keyframes(tmp_path)[0].scene_id
    b = group_keyframes(tmp_path)[0].scene_id
    assert a == b
    assert a.startswith("gen_")


def test_non_images_ignored(tmp_path):
    _touch(tmp_path, "vid_scene_001_frame_00.jpg")
    (tmp_path / "notes.txt").write_text("ignore me")
    (tmp_path / ".DS_Store").write_bytes(b"\x00")
    scenes = group_keyframes(tmp_path)
    assert len(scenes) == 1


def test_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        group_keyframes(tmp_path / "nope")
