"""Read-only experimental results; never starts a replay or touches production data."""
import json
import re

from fastapi import APIRouter, HTTPException

from src.review_lab.store import lab_root

router = APIRouter(prefix='/review-lab', tags=['Experimental review'])


@router.get('/runs')
def list_review_runs():
    root = lab_root()
    if not root.exists():
        return {'runs': []}
    # One-shot experimental runs only; never enumerate production directories.
    runs = sorted((p for p in root.iterdir()
                   if re.fullmatch(r'friday-[a-f0-9]{32}', p.name) and p.is_dir()),
                  key=lambda p: p.stat().st_mtime, reverse=True)[:50]
    return {'runs': [p.name for p in runs]}


@router.get('/runs/{run_id}')
def get_review_run(run_id: str):
    if not re.fullmatch(r'friday-[a-f0-9]{32}', run_id):
        raise HTTPException(400, 'Invalid review run id')
    root = lab_root().resolve()
    file = root / run_id / 'result.json'
    if not file.exists():
        raise HTTPException(404, 'No experimental result')
    if not file.resolve().is_relative_to(root) or file.stat().st_size > 65536:
        raise HTTPException(400, 'Invalid experimental artifact')
    with file.open('rb') as handle:
        raw = handle.read(65537)
    if len(raw) > 65536:
        raise HTTPException(400, 'Artifact too large')
    try:
        result = json.loads(raw)
        if result.get('reference_only') is not True or result.get('schema_version') != 1:
            raise ValueError('Invalid artifact')
    except (ValueError, AttributeError):
        raise HTTPException(400, 'Invalid experimental artifact') from None
    return result
