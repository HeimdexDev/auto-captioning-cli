"""Stage 1 — ``inspect``: group keyframe files into scenes by filename.

The keyframes dir holds files like ``Dz57B0QkaCU_scene_024_frame_00.jpg``. We
group every frame of one scene together and assign a canonical ``scene_id`` of
``{video_id}__scene_NNN`` (DOUBLE underscore, matching the labelers' index).

Supported naming schemes (tried in order):

  1. ``{video}_scene_NNN_frame_NN.ext``      (this dataset; video may contain "_")
  2. ``{video}__scene_NNN__frame_NN.ext``    (double-underscore variant)
  3. ``{live}__sc_YYY__kf_NN.ext``           (the caption-eval skill's format)

Anything that matches none of these falls back to a deterministic generated id
derived from the filename stem (its trailing frame token, if any, stripped), so
the run is still reproducible.

``video_id`` may itself contain underscores (e.g. ``F_ws4NaorhA``), so the video
portion is matched greedily up to the scene marker.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import IMAGE_MEDIA_TYPES

# {video}_scene_NNN_frame_NN  and  {video}__scene_NNN__frame_NN
_RE_SCENE_FRAME = re.compile(
    r"^(?P<video>.+?)_+scene_(?P<scene>\d+)_+frame_(?P<frame>\d+)$"
)
# {live}__sc_YYY__kf_NN  (skill format)
_RE_SC_KF = re.compile(
    r"^(?P<video>.+?)__sc_(?P<scene>\d+)(?:__kf_(?P<frame>\d+))?$"
)


@dataclass(frozen=True)
class Scene:
    scene_id: str
    video_id: str
    scene_num: int
    keyframe_paths: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "scene_id": self.scene_id,
            "video_id": self.video_id,
            "scene_num": self.scene_num,
            "keyframe_paths": list(self.keyframe_paths),
        }


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_MEDIA_TYPES


def _parse_stem(stem: str) -> tuple[str, int, int, str] | None:
    """Return ``(video_id, scene_num, frame_num, scene_id)`` or ``None``.

    ``scene_id`` preserves the original zero-padded scene token (e.g. ``024``).
    """
    m = _RE_SCENE_FRAME.match(stem)
    if m:
        video = m.group("video")
        scene_tok = m.group("scene")
        frame = int(m.group("frame"))
        return video, int(scene_tok), frame, f"{video}__scene_{scene_tok}"
    m = _RE_SC_KF.match(stem)
    if m:
        video = m.group("video")
        scene_tok = m.group("scene")
        frame = int(m.group("frame") or 0)
        return video, int(scene_tok), frame, f"{video}__sc_{scene_tok}"
    return None


def _fallback_id(stem: str) -> tuple[str, int, int, str]:
    """Deterministic id for files that match no known scheme.

    Strips a trailing ``_frame_NN`` / ``_NN`` token (so multiple frames of the
    same odd scene still group) and hashes the remainder for a stable suffix.
    """
    base = re.sub(r"[_-]+(?:frame[_-]?)?\d+$", "", stem) or stem
    frame_m = re.search(r"(\d+)$", stem)
    frame = int(frame_m.group(1)) if frame_m else 0
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    scene_id = f"gen_{digest}__scene_000"
    return base, 0, frame, scene_id


def group_keyframes(keyframes_dir: Path) -> list[Scene]:
    """Group all image files in ``keyframes_dir`` into deterministically-sorted scenes."""
    keyframes_dir = Path(keyframes_dir)
    if not keyframes_dir.exists():
        raise FileNotFoundError(f"keyframes dir not found: {keyframes_dir}")

    # scene_id -> {video_id, scene_num, frames: [(frame_num, abspath_str)]}
    buckets: dict[str, dict] = {}
    for path in keyframes_dir.iterdir():
        if not path.is_file() or not is_image(path):
            continue
        parsed = _parse_stem(path.stem)
        if parsed is None:
            video, scene_num, frame, scene_id = _fallback_id(path.stem)
        else:
            video, scene_num, frame, scene_id = parsed
        b = buckets.setdefault(
            scene_id, {"video_id": video, "scene_num": scene_num, "frames": []}
        )
        b["frames"].append((frame, str(path.resolve())))

    scenes: list[Scene] = []
    for scene_id, b in buckets.items():
        # sort frames by (frame_num, path) for stable ordering
        frames = sorted(b["frames"], key=lambda fp: (fp[0], fp[1]))
        scenes.append(
            Scene(
                scene_id=scene_id,
                video_id=b["video_id"],
                scene_num=b["scene_num"],
                keyframe_paths=tuple(p for _, p in frames),
            )
        )

    # deterministic global order: video_id, then scene_num, then scene_id
    scenes.sort(key=lambda s: (s.video_id, s.scene_num, s.scene_id))
    return scenes
