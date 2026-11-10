
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from .database import init_db
from .routes import router


FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    init_db()
    yield


app = FastAPI(title="Kirana Voice Khata", lifespan=lifespan)
app.include_router(router)


@app.get("/")
def root():
    index_path = FRONTEND_DIST_DIR / "index.html"
    if index_path.is_file():
        return FileResponse(index_path)
    return {"message": "Kirana Voice Khata API is running"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/{full_path:path}", include_in_schema=False)
def frontend_or_not_found(full_path: str, request: Request):
    normalized_path = full_path.lstrip("/")
    if normalized_path == "api" or normalized_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")

    dist_dir = FRONTEND_DIST_DIR.resolve()
    candidate = (dist_dir / normalized_path).resolve()
    if candidate != dist_dir and dist_dir not in candidate.parents:
        raise HTTPException(status_code=404, detail="Not Found")
    if candidate.is_file():
        return FileResponse(candidate)

    if "text/html" in request.headers.get("accept", "").lower():
        index_path = dist_dir / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Not Found")
