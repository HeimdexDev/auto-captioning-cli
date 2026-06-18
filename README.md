# Heimdex caption viewer

A review tool for a Korean live-commerce caption dataset. For each video **scene**
it plays a short **video clip** of that scene and compares the **human** labeler
caption against **Claude-generated** captions (3 references per scene, written
from different perspectives).

A pure-Python pipeline feeds a no-build web viewer:

```
inspect -> build-jobs -> generate -> validate -> build-comparison -> make-clips -> resolve-media -> serve
```

The viewer (`web/`) is **stdlib-only** -- it serves with zero pip installs, which
is all Replit needs to run it.

---

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # pipeline deps (NOT needed to serve)
# create .env with the keys below

python -m heimdex_ptp --help              # list all stages
pytest -q                                 # scene grouping + prompt determinism + join
```

Serving the UI needs **none** of the above -- just the standard library:

```bash
python3 web/server.py            # http://localhost:5000
```

---

## The pipeline (`python -m heimdex_ptp <command>`)

| Stage | What it does |
|-------|--------------|
| `inspect` | Scan the keyframes dir, group files into scenes by filename (`{video_id}_scene_NNN_frame_NN.jpg` -> scene_id `{video_id}__scene_NNN`). Deterministic order. |
| `build-jobs` | Emit one JSONL job per scene: scene_id, absolute keyframe paths, skill file paths, an output target, and a rendered prompt (the COMBINED single-scene caption-eval schema -- 3 refs `ref_a`/`ref_b`/`ref_c`). |
| `generate` | One Claude (`claude-opus-4-8`) Messages request per scene: the skill as a **cached** system block + the prompt + keyframes as base64 images, constrained to the schema via `output_config.format`. Writes `data/generated/<scene_id>.json`. Cost guards: `--dry-run`, `--limit N`, skip-if-exists (`--overwrite`). |
| `validate` | Subprocess to the skill's authoritative `validate_output.py` (caption length 30-80, enums, exactly 3 refs). Structured output can't enforce length, so always validate after generate. Propagates the validator's exit code. |
| `build-comparison` | Join the human-caption JSONL with the generated files into viewer entries (union of scene_ids). |
| `make-clips` | **Recover scene timing** (the dataset has none): perceptual-hash each scene's keyframes and match them against frames sampled from the full source video (~2 fps) to find real start/end, ffmpeg-cut the clip (H.264 + faststart, ~1.5s pad, <=20s), and upload to `s3://heimdex-video-archive-raw/clips/<video_id>/<scene_id>.mp4`. Emits `data/clip_keys.json` (S3 keys + times only -- safe to commit). |
| `extract-frames` | Sample N frames evenly ACROSS each recovered clip (adaptive ~1 frame/2.5s, min 4 / max 12) and perceptual-hash dedup near-identical ones. The dataset's 2-3 labeler keyframes sit at the clip ends and miss the middle of long scenes; these clip-spanning frames become the captioning input so captions reflect the WHOLE clip. Downloads the small per-scene clip (ambient creds). |
| `resolve-media` | Bake **presigned** GET URLs into the comparison JSON: keyframes, the full source video, the per-scene clip (`video_url`), and the subtitle. |
| `serve` | Start the stdlib web viewer. |

### Full run

```bash
# 1) recover per-scene clip bounds + upload viewer clips
python -m heimdex_ptp make-clips        --comparison data/comparison.live.json
# (make-clips needs a scene list; on a first run, build a comparison from build-comparison
#  with no media, or pass the scenes you want — see make-clips --help)
# 2) sample clip-spanning caption frames from those clips
python -m heimdex_ptp extract-frames    --clips data/clip_keys.json
# 3) build jobs (auto-uses data/caption_frames.json when present), then caption
python -m heimdex_ptp build-jobs        --out data/caption_jobs.jsonl
python -m heimdex_ptp generate          --jobs data/caption_jobs.jsonl --limit 3
python -m heimdex_ptp validate          data/generated/<scene_id>.json
python -m heimdex_ptp build-comparison  --human data/human_captions.jsonl \
                                        --out data/comparison.live.json
python -m heimdex_ptp resolve-media     --comparison data/comparison.live.json \
                                        --clips data/clip_keys.json
python -m heimdex_ptp serve
```

---

## Viewer data contract (`GET /api/comparison`)

`resolve-media` writes an array of entries; the UI reads it and tolerates any
null field.

```jsonc
{
  "scene_id": "Dz57B0QkaCU__scene_024",
  "video_id": "Dz57B0QkaCU",
  "video_url": "https://.../clips/...scene_024.mp4?X-Amz-...",  // presigned CLIP (full source if no clip; may be null)
  "full_video_url": "https://.../Dz57B0QkaCU.mp4?X-Amz-...",    // optional "전체 영상"
  "clip_start": 83.7, "clip_end": 86.7,                          // clip location in source (null if no clip)
  "keyframes": ["https://...frame_00.jpg?X-Amz-...", "..."],    // presigned scene keyframes
  "subtitle_url": "https://...ko.vtt?X-Amz-...",                 // optional, may be null
  "human_caption": "...",                                        // may be null
  "claude_references": [                                          // exactly 3: ref_a/b/c (temporal lenses)
    { "ref_id":"ref_a","caption":"...","shot_type":"...","motion_type":"...",
      "temporal_change":"...","text_on_screen":["..."]|null,"mood":["..."]|null,"notes":"" }
  ],
  "quality_notes": { "human_strength":"","claude_strength":"","claude_failure_modes":[] }
}
```

The UI plays `video_url` in a 16:9 frame with a graceful fallback chain:
**clip -> first keyframe `<img>` -> photo placeholder**. The AI card defaults to
`ref_a` with a 행동 / 공간 / 요약 toggle (action-flow / spatial-and-camera /
narrative-arc) to view all three temporal lenses.

A committed `data/comparison.sample.json` (full shape, placeholder non-token
URLs) lets the UI render before any live data exists.

---

## Configuration (`.env`, gitignored)

```
ANTHROPIC_API_KEY=sk-ant-...
AWS_ACCESS_KEY_ID=AKIA...        # the scoped read-only replit-caption-viewer key
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=ap-northeast-2
```

`.env` is loaded **without overriding** values already in the environment, so
host Secrets (Replit) and exported shell vars always win.

---

## Deploy to Replit

1. **Import the repo** into Replit.
2. **Upload `data/comparison.live.json`** into the Repl (it is gitignored -- see
   below). The server auto-prefers `comparison.live.json` over the committed
   `comparison.sample.json`.
3. **Press Run.** `.replit` runs `python3 web/server.py`, which binds `0.0.0.0`
   on `$PORT` (default 5000). No pip install, no AWS credentials on the host --
   the browser loads media straight from the presigned URLs in the JSON.

For the **live "try it" captioning gallery** (users click to generate captions):
4. Set `ANTHROPIC_API_KEY` as a Replit **Secret** (stays server-side; never sent to
   the browser). Replit installs `anthropic` from requirements.txt.
5. Upload `data/catalog.live.json` (gitignored — presigned, built offline) into the
   Repl's `data/` folder. The gallery then lists the curated scenes and the
   `AI 캡션 생성` button calls `POST /api/caption`.

---

## Try-it: live AI captioning gallery

A second tab ("AI 캡션 체험") shows a curated, uncaptioned scene gallery; clicking
`AI 캡션 생성` generates the 3 temporal references live via Anthropic.

Build the catalog offline (needs the ambient AWS identity for S3 uploads):

```bash
python -m heimdex_ptp curate --n 25 --per-video 5      # -> data/catalog_scenes.json
python -m heimdex_ptp make-clips   --comparison data/catalog_scenes.json \
                                   --out data/clip_keys.catalog.json --fps 1.5
python -m heimdex_ptp extract-frames --clips data/clip_keys.catalog.json \
                                   --out data/caption_frames.catalog.json --upload
python -m heimdex_ptp build-catalog --clips data/clip_keys.catalog.json \
                                   --frames data/caption_frames.catalog.json \
                                   --scene-list data/catalog_scenes.json   # -> data/catalog.live.json
```

`curate` auto-selects N scenes across the fewest, most category-diverse videos (to
minimize source downloads). `extract-frames --upload` pushes the clip-spanning frames
to S3 so the server can fetch them by presigned URL.

**Endpoint + guardrails** (`POST /api/caption {scene_id}`): the key lives only on the
server; results are **cached per scene_id** (a scene bills at most once, ever);
requests are **rate-limited per IP** (token bucket) with a **global daily cap**; and
frames-per-request + `max_tokens` are bounded. `anthropic` is lazy-imported, so static
serving still needs zero installs and the gallery degrades gracefully without a key.

## Critical constraints / lessons

- **No scene timing exists anywhere.** Keyframe -> video-frame perceptual-hash
  matching is the only way to recover real clip bounds.
- **Buckets are private.** The browser only ever receives presigned URLs; AWS
  credentials never appear in client code or any committed file.
- **Presigned URLs embed the AWS access-key-id**, which GitHub push-protection
  blocks. So `data/comparison.live.json` is **gitignored** and delivered to
  Replit out-of-band; only the placeholder `comparison.sample.json` is committed.
- **Two credential identities, on purpose.** `make-clips` uses the **ambient**
  AWS identity (needs `PutObject`); `resolve-media` signs with the **scoped
  read-only key from `.env`** (long-lived `AKIA` -> full 7-day presign; ambient
  STS creds would expire in hours). Don't cross them.
- **Korean NFC vs NFD.** Every S3 key is derived from the URL strings in
  `scenes.jsonl` -- never retype Korean channel names into paths.
- **Always validate after generate.** Structured outputs strip caption
  length constraints; the Python validator enforces 30-80 chars.
- **The skill is sent as a cached system block** (one cache write, then cheap
  reads for every subsequent scene).
- **Subtitles (`<track>`) need CORS.** Cross-origin WebVTT from S3 won't load
  without a bucket CORS policy (the clip itself plays fine); subtitles are
  best-effort and optional.

---

## Layout

```
heimdex_ptp/        pipeline package (one submodule per stage)
  scenes.py         inspect -- scene grouping
  jobs.py           build-jobs -- job + prompt rendering
  generate.py       generate -- Claude vision call (cached skill, structured output)
  validate.py       validate -- subprocess to the skill validator
  comparison.py     build-comparison -- human vs Claude join
  clips.py          make-clips -- timing recovery + ffmpeg + S3 upload (ambient creds)
  media.py          resolve-media -- presign (scoped .env key)
  config.py         shared constants + .env loader + S3-URL parsing
  __main__.py       argparse dispatcher
web/
  index.html        no-build React 18 + Babel viewer (video clip per scene)
  server.py         stdlib-only HTTP server (zero pip installs)
tests/              pytest: scene grouping + prompt determinism + comparison join
data/
  comparison.sample.json   committed placeholder (full shape, non-token URLs)
  comparison.live.json     GITIGNORED -- presigned URLs, upload out-of-band
```
