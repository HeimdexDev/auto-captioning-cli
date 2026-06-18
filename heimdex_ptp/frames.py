"""Stage — ``extract-frames``: sample caption frames across each recovered clip.

The dataset's 2–3 labeler keyframes sit at the clip ENDS and miss the middle of
longer scenes (a 20s scene comes with 2 frames). ``make-clips`` already recovered
each scene's bounds and uploaded a per-scene clip that spans the whole scene, so we
sample N frames evenly ACROSS that clip, perceptual-hash dedup near-identical
frames, and save them locally. The captioning step then uses these instead of the
sparse dataset keyframes, so the captions reflect the WHOLE clip.

Frame budget is adaptive: ~1 frame per ``--secs-per-frame``, clamped to
[``--min-frames``, ``--max-frames``]. We download the small per-scene clip (not the
full source) with the ambient AWS identity.

Requires ffmpeg/ffprobe and ``boto3 imagehash Pillow``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import RAW_BUCKET


def _eprint(*a: object) -> None:
    print(*a, file=sys.stderr)


def frame_count_for_duration(
    duration: float, secs_per_frame: float = 2.5, lo: int = 4, hi: int = 12
) -> int:
    """Adaptive frame count: ~1 frame per ``secs_per_frame``, clamped to [lo, hi]."""
    if duration <= 0:
        return lo
    n = round(duration / secs_per_frame)
    return max(lo, min(hi, int(n)))


def even_timestamps(duration: float, n: int) -> list[float]:
    """``n`` evenly-spaced timestamps across [0, duration], endpoints included."""
    if n <= 1:
        return [0.0]
    return [round(duration * i / (n - 1), 3) for i in range(n)]


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _extract_at(video: Path, t: float, out: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(video),
         "-frames:v", "1", "-q:v", "3", str(out)],
        capture_output=True, check=True,
    )


def _dedup_indices(frame_paths: list[Path], threshold: int = 8) -> list[int]:
    """Keep the first frame, then any frame far enough (Hamming > threshold) from the
    last kept one; always keep the final frame. Collapses static stretches."""
    import imagehash
    from PIL import Image

    n = len(frame_paths)
    if n <= 2:
        return list(range(n))
    hashes = [imagehash.phash(Image.open(p)) for p in frame_paths]
    kept = [0]
    for i in range(1, n - 1):
        if (hashes[i] - hashes[kept[-1]]) > threshold:
            kept.append(i)
    if (n - 1) not in kept:
        kept.append(n - 1)
    return kept


def extract_frames(
    clips_path: Path,
    *,
    out_dir: Path = Path("data/caption_frames"),
    frames_out: Path = Path("data/caption_frames.json"),
    secs_per_frame: float = 2.5,
    min_frames: int = 4,
    max_frames: int = 12,
    dedup_threshold: int = 8,
) -> dict[str, dict]:
    """Sample + dedup caption frames for every scene in ``clip_keys.json``."""
    import boto3

    clips = json.loads(Path(clips_path).read_text(encoding="utf-8"))
    s3 = boto3.client("s3")  # ambient identity (download only)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for sid, info in clips.items():
            clip_key = info["clip_key"]
            local = tmp / f"{sid}.mp4"
            _eprint(f"downloading clip {clip_key} ...")
            s3.download_file(RAW_BUCKET, clip_key, str(local))
            dur = _ffprobe_duration(local)
            n = frame_count_for_duration(dur, secs_per_frame, min_frames, max_frames)
            ts = even_timestamps(dur, n)

            raw: list[tuple[float, Path]] = []
            for i, t in enumerate(ts):
                # clamp slightly inside to avoid an EOF black frame
                tt = min(t, max(0.0, dur - 0.05))
                p = tmp / f"{sid}_{i:02d}.jpg"
                _extract_at(local, tt, p)
                raw.append((tt, p))

            kept = _dedup_indices([p for _, p in raw], dedup_threshold)

            scene_dir = out_dir / sid
            scene_dir.mkdir(parents=True, exist_ok=True)
            # clear any stale frames from a previous run
            for old in scene_dir.glob("*.jpg"):
                old.unlink()
            frames = []
            for j, idx in enumerate(kept):
                t, src = raw[idx]
                dst = scene_dir / f"{j:02d}.jpg"
                dst.write_bytes(Path(src).read_bytes())
                frames.append({"path": str(dst.resolve()), "t": round(t, 2)})

            result[sid] = {
                "clip_key": clip_key,
                "duration": round(dur, 2),
                "n_sampled": len(ts),
                "n_kept": len(frames),
                "frames": frames,
            }
            _eprint(f"  {sid}: {dur:.1f}s clip -> sampled {len(ts)}, kept {len(frames)} frames")

    frames_out = Path(frames_out)
    frames_out.parent.mkdir(parents=True, exist_ok=True)
    frames_out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _eprint(f"wrote {len(result)} scene frame-set(s) -> {frames_out}")
    return result


def load_frames_map(path: Path) -> dict[str, dict]:
    """Load caption_frames.json (empty dict if missing)."""
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
