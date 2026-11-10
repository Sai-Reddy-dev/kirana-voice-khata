
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import base64
import hmac
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .database import init_db
from .routes import router


FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    init_db()
    yield


app = FastAPI(title="Kirana Voice Khata", lifespan=lifespan)
app.include_router(router)


@app.middleware("http")
async def demo_access(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    running_on_render = os.getenv("RENDER", "").strip().lower() == "true"
    auth_configured = os.getenv("DEMO_AUTH_REQUIRED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    auth_required = running_on_render or auth_configured
    if not auth_required:
        return await call_next(request)

    username = os.getenv("DEMO_USERNAME")
    password = os.getenv("DEMO_PASSWORD")
    if not username or not password:
        return JSONResponse(
            status_code=503,
            content={"detail": "Demo access is not configured"},
        )

    authorization = request.headers.get("authorization", "")
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() != "basic" or not credentials:
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
            headers={"WWW-Authenticate": 'Basic realm="Kirana Voice Khata Demo"'},
        )

    try:
        decoded = base64.b64decode(credentials, validate=True).decode("utf-8")
        supplied_username, separator, supplied_password = decoded.partition(":")
    except (ValueError, UnicodeDecodeError):
        separator = ""
        supplied_username = ""
        supplied_password = ""

    username_matches = hmac.compare_digest(
        supplied_username.encode("utf-8"), username.encode("utf-8")
    )
    password_matches = hmac.compare_digest(
        supplied_password.encode("utf-8"), password.encode("utf-8")
    )
    if not separator or not (username_matches and password_matches):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
            headers={"WWW-Authenticate": 'Basic realm="Kirana Voice Khata Demo"'},
        )

    return await call_next(request)


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
