"""Stage 6 — ``make-clips``: recover scene timing and cut per-scene clips.

The dataset has NO scene timing. But each scene's keyframes were extracted FROM
the full source video, so we recover the timing: perceptual-hash every frame of
the video (sampled at ``--fps``) and match each scene's first/last keyframe back
to it to find real start/end times. Then ffmpeg-cuts the clip (re-encoded H.264
+ faststart, padded, capped) and uploads it to
``s3://heimdex-video-archive-raw/clips/<video_id>/<scene_id>.mp4``.

Output: ``data/clip_keys.json`` mapping ``scene_id -> {clip_key, start, end,
video_key}`` — S3 keys + times only, safe to commit.

Credentials: uses the DEFAULT AWS chain (the machine's ``aws`` identity) for
download AND upload — it does NOT read ``.env``. The scoped read-only key in
``.env`` (used by ``resolve-media`` for presigning) cannot PutObject, by design.

Requires: ffmpeg/ffprobe on PATH, and ``boto3 imagehash Pillow``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import DEFAULT_KEYFRAMES_DIR, RAW_BUCKET, s3key_from_url


def _eprint(*a: object) -> None:
    print(*a, file=sys.stderr)


def load_scenes_index(path: Path) -> dict[str, dict]:
    """Map scene_id -> row from the labelers' scenes.jsonl."""
    by_id: dict[str, dict] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("scene_id"):
            by_id[r["scene_id"]] = r
    return by_id


def ffprobe_duration(video: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(video),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def extract_frame_hashes(video: Path, outdir: Path, fps: float):
    """Sample the video at ``fps`` and phash each frame -> [(time_sec, hash)]."""
    import imagehash
    from PIL import Image

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video), "-vf", f"fps={fps}", "-q:v", "3",
            str(outdir / "f_%06d.jpg"),
        ],
        capture_output=True, check=True,
    )
    frames = []
    for f in sorted(outdir.glob("f_*.jpg")):
        n = int(f.stem.split("_")[1])
        t = (n - 1) / fps
        frames.append((t, imagehash.phash(Image.open(f))))
    return frames


def cut_clip(video: Path, start: float, dur: float, out: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(video), "-t", f"{dur:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-movflags", "+faststart", str(out),
        ],
        capture_output=True, check=True,
    )


def make_clips(
    comparison_path: Path,
    scenes_jsonl: Path,
    *,
    keyframes_dir: Path = DEFAULT_KEYFRAMES_DIR,
    out: Path = Path("data/clip_keys.json"),
    prefix: str = "clips",
    fps: float = 2.0,
    pad_sec: float = 1.5,
    max_clip_sec: float = 20.0,
    min_clip_sec: float = 3.0,
) -> dict[str, dict]:
    """Recover timing, cut clips, upload to S3, and write the clip-keys map."""
    import boto3
    import imagehash
    from PIL import Image

    keyframes_dir = Path(keyframes_dir)
    scene_ids = [
        e["scene_id"]
        for e in json.loads(Path(comparison_path).read_text(encoding="utf-8"))
    ]
    scenes = load_scenes_index(scenes_jsonl)
    s3 = boto3.client("s3")  # DEFAULT chain (needs Get+Put) — do NOT load .env

    # group by video_id, preserving order
    by_video: dict[str, list[str]] = {}
    for sid in scene_ids:
        if sid in scenes:
            by_video.setdefault(sid.split("__")[0], []).append(sid)
        else:
            _eprint(f"  no scenes.jsonl match for {sid}; skipping")

    result: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for video_id, sids in by_video.items():
            kf_key = s3key_from_url(scenes[sids[0]]["keyframe_urls"][0])
            category, channel, _ = kf_key.split("/")[:3]
            vkey = f"raw/{category}/{channel}/{video_id}.mp4"

            vpath = tmp / f"{video_id}.mp4"
            _eprint(f"downloading {vkey} ...")
            s3.download_file(RAW_BUCKET, vkey, str(vpath))
            dur = ffprobe_duration(vpath)

            framedir = tmp / f"frames_{video_id}"
            framedir.mkdir(exist_ok=True)
            _eprint(f"hashing frames @ {fps}fps ({dur:.0f}s video) ...")
            frames = extract_frame_hashes(vpath, framedir, fps)

            for sid in sids:
                scene_part = sid.split("__")[1]  # e.g. scene_024
                kfs = sorted(
                    keyframes_dir.glob(f"{video_id}_{scene_part}_frame_*.jpg")
                )
                if not kfs:
                    _eprint(
                        f"  no local keyframes for {sid} ({keyframes_dir}); skipping"
                    )
                    continue
                times = []
                for kf in (kfs[0], kfs[-1]):
                    h = imagehash.phash(Image.open(kf))
                    best_t, _ = min(frames, key=lambda ft: ft[1] - h)
                    times.append(best_t)
                start = max(0.0, min(times) - 0.3)
                end = min(dur, max(times) + pad_sec)
                if end - start < min_clip_sec:
                    end = min(dur, start + min_clip_sec)
                if end - start > max_clip_sec:
                    end = start + max_clip_sec

                clip = tmp / f"{sid}.mp4"
                cut_clip(vpath, start, end - start, clip)
                clip_key = f"{prefix}/{video_id}/{sid}.mp4"
                s3.upload_file(
                    str(clip), RAW_BUCKET, clip_key,
                    ExtraArgs={"ContentType": "video/mp4"},
                )
                result[sid] = {
                    "clip_key": clip_key,
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "video_key": vkey,
                }
                _eprint(
                    f"  {sid}: {start:.1f}-{end:.1f}s -> s3://{RAW_BUCKET}/{clip_key}"
                )

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _eprint(f"wrote {len(result)} clip key(s) -> {out}")
    return result
