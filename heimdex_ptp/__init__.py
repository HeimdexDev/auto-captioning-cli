"""heimdex_ptp — pure-Python pipeline for the Heimdex caption-eval review tool.

Stages (run as ``python -m heimdex_ptp <command>``):

    inspect          group keyframes into scenes by filename
    build-jobs       emit one Claude captioning job per scene (with prompt)
    generate         call Claude (vision) for 3 references per scene
    validate         run the skill's authoritative output validator
    build-comparison join human vs Claude captions into viewer entries
    make-clips       recover scene timing + cut/upload per-scene clips
    resolve-media    bake presigned S3 URLs into the comparison JSON
    serve            start the stdlib web viewer

The web viewer (``web/server.py``) is stdlib-only and needs none of the
pipeline dependencies to run.
"""

__version__ = "0.1.0"
