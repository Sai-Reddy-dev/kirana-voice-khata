
from fastapi import FastAPI

app = FastAPI(title="Kirana Voice Khata")


@app.get("/")
def root():
    return {"message": "Kirana Voice Khata API is running"}


@app.get("/health")
def health():
    return {"status": "ok"}
