"""``python -m heimdex_ptp <command>`` — argparse dispatcher for all stages."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import __version__
from .config import (
    DEFAULT_KEYFRAMES_DIR,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_SCENES_JSONL,
    DEFAULT_SKILL_DIR,
    MAX_EXPIRES,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_SERVER = REPO_ROOT / "web" / "server.py"


# ---------------------------------------------------------------------------
# Stage handlers
# ---------------------------------------------------------------------------

def cmd_inspect(args: argparse.Namespace) -> int:
    from .scenes import group_keyframes

    scenes = group_keyframes(args.keyframes)
    if args.json:
        print(json.dumps([s.to_dict() for s in scenes], ensure_ascii=False, indent=2))
    else:
        for s in scenes:
            print(f"{s.scene_id}\t{len(s.keyframe_paths)} frame(s)")
        print(f"\n{len(scenes)} scene(s) across "
              f"{len({s.video_id for s in scenes})} video(s)", file=sys.stderr)
    return 0


def cmd_build_jobs(args: argparse.Namespace) -> int:
    from .frames import load_frames_map
    from .jobs import build_jobs, write_jobs

    frames_map = load_frames_map(args.frames) if args.frames else {}
    jobs = build_jobs(
        args.keyframes, args.skill_dir, args.generated_dir, args.limit, frames_map
    )
    n_with_frames = sum(
        1 for j in jobs if frames_map.get(j["scene_id"], {}).get("frames")
    )
    write_jobs(jobs, args.out)
    print(
        f"wrote {len(jobs)} job(s) ({n_with_frames} using extracted clip frames) "
        f"-> {args.out}",
        file=sys.stderr,
    )
    return 0


def cmd_extract_frames(args: argparse.Namespace) -> int:
    from .frames import extract_frames

    extract_frames(
        args.clips,
        out_dir=args.out_dir,
        frames_out=args.out,
        secs_per_frame=args.secs_per_frame,
        min_frames=args.min_frames,
        max_frames=args.max_frames,
        dedup_threshold=args.dedup_threshold,
    )
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    from .generate import run_generate
    from .jobs import read_jobs

    jobs = read_jobs(args.jobs)
    return run_generate(
        jobs,
        args.out_dir,
        model=args.model,
        max_tokens=args.max_tokens,
        limit=args.limit,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        env_dirs=[args.jobs.resolve().parent],
    )


def cmd_validate(args: argparse.Namespace) -> int:
    from .validate import validate_file

    return validate_file(args.input, args.skill_dir)


def cmd_build_comparison(args: argparse.Namespace) -> int:
    from .comparison import (
        build_comparison,
        load_generated,
        load_human_captions,
        write_comparison,
    )

    human = load_human_captions(args.human)
    generated = load_generated(args.generated_dir)
    entries = build_comparison(human, generated)
    write_comparison(entries, args.out, pretty=not args.compact)
    print(
        f"wrote {len(entries)} entr(ies) "
        f"({len(human)} human, {len(generated)} generated) -> {args.out}",
        file=sys.stderr,
    )
    return 0


def cmd_make_clips(args: argparse.Namespace) -> int:
    from .clips import make_clips

    make_clips(
        args.comparison,
        args.scenes,
        keyframes_dir=args.keyframes,
        out=args.out,
        prefix=args.prefix,
        fps=args.fps,
        pad_sec=args.pad_sec,
        max_clip_sec=args.max_clip_sec,
        min_clip_sec=args.min_clip_sec,
    )
    return 0


def cmd_resolve_media(args: argparse.Namespace) -> int:
    from .media import resolve_media

    return resolve_media(
        args.comparison,
        args.scenes,
        clips_path=args.clips,
        out_path=args.out,
        expires=args.expires,
        env_dirs=[REPO_ROOT],
    )


def cmd_serve(args: argparse.Namespace) -> int:
    if not WEB_SERVER.exists():
        print(f"ERROR: web server not found: {WEB_SERVER}", file=sys.stderr)
        return 2
    cmd = [sys.executable, str(WEB_SERVER), "--port", str(args.port)]
    return subprocess.call(cmd)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="heimdex_ptp",
        description="Pipeline for the Heimdex caption-eval review tool.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    # inspect
    sp = sub.add_parser("inspect", help="group keyframes into scenes")
    sp.add_argument("--keyframes", type=Path, default=DEFAULT_KEYFRAMES_DIR)
    sp.add_argument("--json", action="store_true", help="emit full JSON")
    sp.set_defaults(func=cmd_inspect)

    # build-jobs
    sp = sub.add_parser("build-jobs", help="emit one captioning job per scene")
    sp.add_argument("--keyframes", type=Path, default=DEFAULT_KEYFRAMES_DIR)
    sp.add_argument("--skill-dir", type=Path, default=DEFAULT_SKILL_DIR)
    sp.add_argument("--out", type=Path, default=Path("data/caption_jobs.jsonl"))
    sp.add_argument("--generated-dir", type=Path, default=Path("data/generated"),
                    help="where generate will write outputs (used for output_target)")
    sp.add_argument("--limit", type=int, default=None)
    sp.add_argument("--frames", type=Path, default=Path("data/caption_frames.json"),
                    help="caption_frames.json from extract-frames; clip-spanning frames "
                         "replace dataset keyframes when present (ignored if missing)")
    sp.set_defaults(func=cmd_build_jobs)

    # generate
    sp = sub.add_parser("generate", help="call Claude for 3 references per scene")
    sp.add_argument("--jobs", type=Path, default=Path("data/caption_jobs.jsonl"))
    sp.add_argument("--out-dir", type=Path, default=Path("data/generated"))
    sp.add_argument("--model", default=DEFAULT_MODEL)
    sp.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    sp.add_argument("--limit", type=int, default=None, help="caption first N jobs")
    sp.add_argument("--overwrite", action="store_true")
    sp.add_argument("--dry-run", action="store_true", help="no API call")
    sp.set_defaults(func=cmd_generate)

    # validate
    sp = sub.add_parser("validate", help="run the skill's output validator")
    sp.add_argument("input", type=Path, help="a .json scene/wrapper or .jsonl")
    sp.add_argument("--skill-dir", type=Path, default=DEFAULT_SKILL_DIR)
    sp.set_defaults(func=cmd_validate)

    # build-comparison
    sp = sub.add_parser("build-comparison", help="join human vs generated")
    sp.add_argument("--human", type=Path, default=Path("data/human_captions.jsonl"))
    sp.add_argument("--generated-dir", type=Path, default=Path("data/generated"))
    sp.add_argument("--out", type=Path, default=Path("data/comparison.live.json"))
    sp.add_argument("--compact", action="store_true", help="no pretty indent")
    sp.set_defaults(func=cmd_build_comparison)

    # extract-frames
    sp = sub.add_parser("extract-frames",
                        help="sample clip-spanning caption frames (adaptive + dedup)")
    sp.add_argument("--clips", type=Path, default=Path("data/clip_keys.json"))
    sp.add_argument("--out-dir", type=Path, default=Path("data/caption_frames"))
    sp.add_argument("--out", type=Path, default=Path("data/caption_frames.json"))
    sp.add_argument("--secs-per-frame", type=float, default=2.5)
    sp.add_argument("--min-frames", type=int, default=4)
    sp.add_argument("--max-frames", type=int, default=12)
    sp.add_argument("--dedup-threshold", type=int, default=8,
                    help="phash Hamming distance below which adjacent frames are dropped")
    sp.set_defaults(func=cmd_extract_frames)

    # make-clips
    sp = sub.add_parser("make-clips", help="recover timing + cut/upload clips")
    sp.add_argument("--comparison", type=Path, default=Path("data/comparison.live.json"))
    sp.add_argument("--scenes", type=Path, default=DEFAULT_SCENES_JSONL)
    sp.add_argument("--keyframes", type=Path, default=DEFAULT_KEYFRAMES_DIR)
    sp.add_argument("--out", type=Path, default=Path("data/clip_keys.json"))
    sp.add_argument("--prefix", default="clips")
    sp.add_argument("--fps", type=float, default=2.0)
    sp.add_argument("--pad-sec", type=float, default=1.5)
    sp.add_argument("--max-clip-sec", type=float, default=20.0)
    sp.add_argument("--min-clip-sec", type=float, default=3.0)
    sp.set_defaults(func=cmd_make_clips)

    # resolve-media
    sp = sub.add_parser("resolve-media", help="presign media into the comparison JSON")
    sp.add_argument("--comparison", type=Path, default=Path("data/comparison.live.json"))
    sp.add_argument("--scenes", type=Path, default=DEFAULT_SCENES_JSONL)
    sp.add_argument("--clips", type=Path, default=Path("data/clip_keys.json"))
    sp.add_argument("--out", type=Path, default=None, help="default: overwrite --comparison")
    sp.add_argument("--expires", type=int, default=MAX_EXPIRES,
                    help=f"URL lifetime sec (max {MAX_EXPIRES})")
    sp.set_defaults(func=cmd_resolve_media)

    # serve
    sp = sub.add_parser("serve", help="start the stdlib web viewer")
    sp.add_argument("--port", type=int, default=5000)
    sp.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
