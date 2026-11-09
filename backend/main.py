
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .database import init_db
from .routes import router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    init_db()
    yield


app = FastAPI(title="Kirana Voice Khata", lifespan=lifespan)
app.include_router(router)


@app.get("/")
def root():
    return {"message": "Kirana Voice Khata API is running"}


@app.get("/health")
def health():
    return {"status": "ok"}
