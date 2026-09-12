"""Create or verify the immutable runtime manifest used by deployment."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_PYTHON = PROJECT_ROOT.parent / "shared" / "python"
for candidate in (PROJECT_ROOT, SHARED_PYTHON):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from src.infrastructure.runtime_identity import (  # noqa: E402
    create_manifest,
    validate_manifest,
)


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--output", required=True)
    parser.add_argument("--release-id", default="")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = Path(args.output).resolve()
    if args.verify:
        manifest = validate_manifest(output, root)
    else:
        manifest = create_manifest(root, args.release_id or None)
        _atomic_write(output, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
