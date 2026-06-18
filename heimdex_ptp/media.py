"""Stage 7 — ``resolve-media``: bake presigned S3 URLs into the comparison JSON.

The archive buckets are PRIVATE, so the browser only ever receives time-limited
presigned GET URLs. Per entry we presign:

  keyframes      -> the per-scene keyframe images (keyframes bucket)
  full_video_url -> the full source ``<video_id>.mp4`` (raw bucket)
  subtitle_url   -> ``<video_id>.ko.vtt`` (best-effort)
  video_url      -> the per-scene CLIP if present in clip_keys, else the full source

Every S3 key is derived from the keyframe URLs already in ``scenes.jsonl`` so we
never retype Korean channel names (the NFC/NFD trap).

Credentials: signs with the SCOPED read-only key from ``.env`` (loaded WITHOUT
overriding the real env, so host Secrets win). That long-lived ``AKIA`` key gives
the full 7-day presign lifetime; ambient STS creds would expire in hours.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import MAX_EXPIRES, RAW_BUCKET, load_env_files, url_to_bucket_key


def _eprint(*a: object) -> None:
    print(*a, file=sys.stderr)


def load_scenes_index(path: Path) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        sid = r.get("scene_id")
        if sid:
            by_id[sid] = r
    return by_id


def resolve_media(
    comparison_path: Path,
    scenes_jsonl: Path,
    *,
    clips_path: Path | None = None,
    out_path: Path | None = None,
    expires: int = MAX_EXPIRES,
    env_dirs: list[Path] | None = None,
) -> int:
    """Presign every entry's media and write the resolved comparison JSON."""
    comparison_path = Path(comparison_path)
    scenes_jsonl = Path(scenes_jsonl)

    if expires > MAX_EXPIRES:
        raise SystemExit(f"ERROR: --expires cannot exceed {MAX_EXPIRES} (7-day max)")
    if not comparison_path.exists():
        raise SystemExit(f"ERROR: comparison file not found: {comparison_path}")
    if not scenes_jsonl.exists():
        raise SystemExit(f"ERROR: scenes.jsonl not found: {scenes_jsonl}")

    # Scoped read-only key from .env (long-lived → full 7-day presign).
    candidates = [Path.cwd() / ".env"]
    for d in env_dirs or []:
        candidates.append(Path(d) / ".env")
    load_env_files(*candidates)

    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError as e:
        raise SystemExit("ERROR: boto3 is required (pip install boto3).") from e

    entries = json.loads(comparison_path.read_text(encoding="utf-8"))
    scenes = load_scenes_index(scenes_jsonl)
    clips = (
        json.loads(Path(clips_path).read_text(encoding="utf-8"))
        if clips_path and Path(clips_path).exists()
        else {}
    )

    base = boto3.client("s3")
    clients: dict[str, object] = {}

    def region_of(bucket: str) -> str:
        loc = base.get_bucket_location(Bucket=bucket).get("LocationConstraint")
        return loc or "us-east-1"

    def client_for(bucket: str):
        if bucket not in clients:
            clients[bucket] = boto3.client("s3", region_name=region_of(bucket))
        return clients[bucket]

    def presign(bucket: str, key: str) -> str:
        return client_for(bucket).generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires
        )

    def exists(bucket: str, key: str) -> bool:
        try:
            client_for(bucket).head_object(Bucket=bucket, Key=key)
            return True
        except ClientError:
            return False

    video_cache: dict[str, dict] = {}
    resolved = missing_scene = missing_video = 0

    for entry in entries:
        sid = entry.get("scene_id")
        sc = scenes.get(sid)
        if not sc or not sc.get("keyframe_urls"):
            _eprint(f"  no scenes.jsonl match for {sid}; leaving media empty")
            missing_scene += 1
            continue

        entry["keyframes"] = [
            presign(*url_to_bucket_key(u)) for u in sc["keyframe_urls"]
        ]

        _kf_bucket, first_key = url_to_bucket_key(sc["keyframe_urls"][0])
        # key = <category>/<channel>/<video_id>/scene_NNN/frame_NN.jpg
        parts = first_key.split("/")
        category, channel, video_id = parts[0], parts[1], parts[2]

        if video_id not in video_cache:
            vkey = f"raw/{category}/{channel}/{video_id}.mp4"
            vtt = f"raw/{category}/{channel}/{video_id}.ko.vtt"
            info = {"video_url": None, "subtitle_url": None}
            if exists(RAW_BUCKET, vkey):
                info["video_url"] = presign(RAW_BUCKET, vkey)
                if exists(RAW_BUCKET, vtt):
                    info["subtitle_url"] = presign(RAW_BUCKET, vtt)
            else:
                _eprint(f"  no raw video for {video_id} ({vkey})")
            video_cache[video_id] = info

        v = video_cache[video_id]
        entry["subtitle_url"] = v["subtitle_url"]
        entry["video_id"] = video_id

        clip = clips.get(sid)
        if clip:
            entry["video_url"] = presign(RAW_BUCKET, clip["clip_key"])
            entry["full_video_url"] = v["video_url"]
            entry["clip_start"] = clip.get("start")
            entry["clip_end"] = clip.get("end")
        else:
            entry["video_url"] = v["video_url"]
            entry["full_video_url"] = None
            entry["clip_start"] = None
            entry["clip_end"] = None

        if entry["video_url"] is None:
            missing_video += 1
        resolved += 1

    out = Path(out_path) if out_path else comparison_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _eprint(
        f"resolved media for {resolved} entr(ies); {missing_scene} unmatched, "
        f"{missing_video} without video -> {out}"
    )
    _eprint(f"presigned URLs valid for {expires}s (~{expires // 86400}d)")
    return 0
