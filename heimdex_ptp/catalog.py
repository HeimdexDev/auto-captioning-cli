"""Stage — ``build-catalog``: presign an UNCAPTIONED scene catalog for the try-it gallery.

Per curated scene, emits a presigned clip URL (gallery video), presigned
clip-spanning frame URLs (what the live caption endpoint sends to Anthropic), a
thumbnail, and the clip bounds — but NO captions (those are generated on demand).

Signs with the SCOPED read-only key from ``.env`` (long-lived AKIA → 7-day presign),
loaded without overriding the real env. Reads clip_keys.json + caption_frames.json
(with frame_key) + scenes.jsonl. Output `data/catalog.live.json` is gitignored
(embeds presigned URLs) and uploaded to the host out-of-band.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import MAX_EXPIRES, RAW_BUCKET, load_env_files, url_to_bucket_key


def _eprint(*a: object) -> None:
    print(*a, file=sys.stderr)


def _load_scenes(path: Path) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("scene_id"):
            by_id[r["scene_id"]] = r
    return by_id


def build_catalog(
    scenes_jsonl: Path,
    clips_path: Path,
    frames_path: Path,
    *,
    scene_list: Path | None = None,
    out: Path = Path("data/catalog.live.json"),
    expires: int = MAX_EXPIRES,
    env_dirs: list[Path] | None = None,
) -> list[dict]:
    if expires > MAX_EXPIRES:
        raise SystemExit(f"ERROR: --expires cannot exceed {MAX_EXPIRES}")
    load_env_files(Path.cwd() / ".env", *[(Path(d) / ".env") for d in (env_dirs or [])])

    import boto3
    from botocore.exceptions import ClientError  # noqa: F401

    scenes = _load_scenes(scenes_jsonl)
    clips = json.loads(Path(clips_path).read_text(encoding="utf-8"))
    frames = json.loads(Path(frames_path).read_text(encoding="utf-8"))

    # which scenes: explicit list, else every scene that has a clip
    if scene_list and Path(scene_list).exists():
        ids = [e["scene_id"] for e in json.loads(Path(scene_list).read_text(encoding="utf-8"))]
    else:
        ids = list(clips.keys())

    base = boto3.client("s3")
    clients: dict[str, object] = {}

    def client_for(bucket: str):
        if bucket not in clients:
            loc = base.get_bucket_location(Bucket=bucket).get("LocationConstraint")
            clients[bucket] = boto3.client("s3", region_name=loc or "us-east-1")
        return clients[bucket]

    def presign(bucket: str, key: str) -> str:
        return client_for(bucket).generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires
        )

    out_entries: list[dict] = []
    skipped = 0
    for sid in ids:
        clip = clips.get(sid)
        fr = frames.get(sid)
        sc = scenes.get(sid)
        if not (clip and fr and sc):
            _eprint(f"  skip {sid}: missing clip/frames/scene")
            skipped += 1
            continue
        video_id = sid.split("__")[0]
        meta = {"category": sc.get("category"), "channel": sc.get("channel")}
        thumb = None
        if sc.get("keyframe_urls"):
            thumb = presign(*url_to_bucket_key(sc["keyframe_urls"][0]))
        frame_urls = [
            presign(RAW_BUCKET, f["frame_key"]) for f in fr["frames"] if f.get("frame_key")
        ]
        out_entries.append({
            "scene_id": sid,
            "video_id": video_id,
            "category": meta["category"],
            "channel": meta["channel"],
            "video_url": presign(RAW_BUCKET, clip["clip_key"]),
            "clip_start": clip.get("start"),
            "clip_end": clip.get("end"),
            "thumbnail": thumb,
            "frames": frame_urls,
            "n_frames": len(frame_urls),
        })

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(out_entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _eprint(f"wrote catalog: {len(out_entries)} scene(s), {skipped} skipped -> {out}")
    _eprint(f"presigned URLs valid for {expires}s (~{expires // 86400}d)")
    return out_entries
