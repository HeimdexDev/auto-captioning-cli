"""Stage 4 — ``validate``: run the skill's authoritative output validator.

Structured outputs cannot enforce caption length, so every generated file must
pass the skill's ``scripts/validate_output.py`` (length 30–80, enums, exactly 3
refs, diversity warnings). We call it as a SUBPROCESS rather than reimplementing
it, and propagate its exit code (0 PASS / WARN-only, 1 FAIL, 2 bad input).

A ``.jsonl`` of per-scene objects is auto-wrapped into ``{"scenes": [...]}`` in a
temp file before validation, since the validator accepts a single scene object
or a ``{"scenes": [...]}`` wrapper.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import DEFAULT_SKILL_DIR


def _validator_path(skill_dir: Path) -> Path:
    p = Path(skill_dir) / "scripts" / "validate_output.py"
    if not p.exists():
        raise FileNotFoundError(f"validator not found: {p}")
    return p


def _wrap_jsonl(path: Path) -> Path:
    """Wrap a JSONL of scene objects into a temp ``{"scenes": [...]}`` file."""
    scenes = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            scenes.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON on line {i} of {path}: {e}") from e
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump({"scenes": scenes}, tmp, ensure_ascii=False)
    tmp.close()
    return Path(tmp.name)


def validate_file(target: Path, skill_dir: Path = DEFAULT_SKILL_DIR) -> int:
    """Validate one ``.json`` scene/wrapper or a ``.jsonl`` of scenes.

    Returns the validator's exit code (0 PASS/WARN, 1 FAIL, 2 bad input).
    """
    target = Path(target)
    if not target.exists():
        print(f"ERROR: file not found: {target}", file=sys.stderr)
        return 2

    validator = _validator_path(skill_dir)

    tmp: Path | None = None
    check_path = target
    if target.suffix == ".jsonl":
        tmp = _wrap_jsonl(target)
        check_path = tmp
    try:
        proc = subprocess.run(
            [sys.executable, str(validator), str(check_path)],
            capture_output=True,
            text=True,
        )
        # Surface the validator's own report verbatim.
        if proc.stdout:
            sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        return proc.returncode
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
