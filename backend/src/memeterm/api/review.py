"""REST endpoint for the weekly review snapshot.

Returns the most recent ``data/snapshots/review_*.json`` file. The
dashboard's /review page reads from here so we never have to re-run the
LLM call to render the page.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()

_SNAP_DIR = Path("data/snapshots")


@router.get("/review/latest")
async def latest_review() -> dict[str, Any]:
    if not _SNAP_DIR.exists():
        raise HTTPException(status_code=404, detail="no snapshots yet")
    candidates = sorted(_SNAP_DIR.glob("review_*.json"), reverse=True)
    if not candidates:
        raise HTTPException(status_code=404, detail="no review snapshots yet")
    try:
        return json.loads(candidates[0].read_text())
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="snapshot corrupt") from exc


@router.get("/review/calibration")
async def latest_calibration() -> dict[str, Any]:
    if not _SNAP_DIR.exists():
        raise HTTPException(status_code=404, detail="no snapshots yet")
    candidates = sorted(_SNAP_DIR.glob("learning_*.json"), reverse=True)
    if not candidates:
        raise HTTPException(status_code=404, detail="no calibration snapshots yet")
    try:
        return json.loads(candidates[0].read_text())
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="snapshot corrupt") from exc
