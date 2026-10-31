"""Static file + image serving (styles, scripts, character/race images, the SPA index).

Fully self-contained: paths are computed from the repo root, there is no shared app state, so this
imports nothing from main.py. Mounted via app.include_router() in main.py.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
PUBLIC_DIR = BASE_DIR / "public"


def _safe_path(root: Path, requested_name: str, detail: str) -> Path:
    """Resolve a user-supplied filename without allowing it to escape ``root``.

    FastAPI's single-segment route converter blocks forward slashes, but on Windows a backslash is
    also a path separator. Resolving and checking containment closes that platform-specific escape,
    as well as absolute paths and symlink traversal.
    """
    safe_root = root.resolve()
    try:
        candidate = (safe_root / str(requested_name or "")).resolve()
        candidate.relative_to(safe_root)
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(status_code=404, detail=detail)
    return candidate


def _existing_file(root: Path, requested_name: str, detail: str) -> Path:
    candidate = _safe_path(root, requested_name, detail)
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=detail)
    return candidate


@router.get("/api/images/{image_name}")
async def get_image(image_name: str):
    name_no_ext = image_name.split('?')[0].replace('.png', '')

    exact_path = _safe_path(IMAGES_DIR, f"{name_no_ext}.png", "Image not found")
    if exact_path.is_file():
        return FileResponse(exact_path, media_type="image/png", headers={"Cache-Control": "no-cache"})

    for fallback_id in ['100101', '10010', '10000', '10001']:
        fb_path = IMAGES_DIR / f"{fallback_id}.png"
        if fb_path.exists():
            return FileResponse(fb_path, media_type="image/png", headers={"Cache-Control": "no-cache"})

    raise HTTPException(status_code=404, detail="Image not found")


@router.get("/styles.css")
async def styles_css():
    path = PUBLIC_DIR / "styles.css"
    if path.exists():
        return FileResponse(path, media_type="text/css", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="styles.css not found")


@router.get("/app.js")
async def app_js():
    path = PUBLIC_DIR / "app.js"
    if path.exists():
        return FileResponse(path, media_type="application/javascript", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="app.js not found")


@router.get("/sweep.png")
async def sweep_png():
    path = PUBLIC_DIR / "sweep.png"
    if path.exists():
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="sweep.png not found")


@router.get("/broom.png")
async def broom_png():
    path = PUBLIC_DIR / "broom.png"
    if path.exists():
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="broom.png not found")


@router.get("/assets/data/{file_name}")
async def get_asset_data(file_name: str):
    path = _existing_file(PUBLIC_DIR / "assets" / "data", file_name, "File not found")
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@router.get("/races/{file_name}")
async def get_race_image(file_name: str):
    path = _existing_file(PUBLIC_DIR / "races", file_name, "Race image not found")
    return FileResponse(path, headers={"Cache-Control": "max-age=31536000"})


@router.get("/", response_class=HTMLResponse)
async def root():
    index_path = PUBLIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path, media_type="text/html", headers={"Cache-Control": "no-cache"})
    return "index.html not found"
