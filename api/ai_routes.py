"""Closed-loop AI-learning routes: status / train / reset / export / import of the learned brain.

Delegates entirely to career_bot.ai_learn and is self-contained (computes its own base dir, no shared
app state). Mounted via app.include_router() in main.py.
"""
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from career_bot.core import ai_learn

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent


@router.get("/api/ai/status")
async def ai_status():
    return ai_learn.status(BASE_DIR)


@router.post("/api/ai/train")
async def ai_train():
    return ai_learn.train(BASE_DIR)


@router.post("/api/ai/reset")
async def ai_reset():
    return ai_learn.reset(BASE_DIR)


@router.post("/api/ai/export")
async def ai_export(password: str = Form("")):
    if not (password or "").strip():
        raise HTTPException(status_code=400, detail="Owner password is required to export an encrypted brain")
    path = ai_learn.export_brain(BASE_DIR, password)
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Failed to export AI brain")
    return FileResponse(path, media_type="application/octet-stream", filename=Path(path).name)


@router.post("/api/ai/import")
async def ai_import(file: UploadFile = File(...), password: str = Form("")):
    tmp_path = None
    try:
        data = await file.read()
        fd, tmp_path = tempfile.mkstemp(suffix=".zip", prefix="ai-brain-import-")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return ai_learn.import_brain(BASE_DIR, tmp_path, password)
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
