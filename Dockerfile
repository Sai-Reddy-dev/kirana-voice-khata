FROM node:22-bookworm-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg gosu libportaudio2 libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY prompts/ ./prompts/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/data /var/data \
    && chown -R app:app /app/data /var/data

EXPOSE 10000
CMD ["sh", "-c", "chown app:app /var/data && exec gosu app uvicorn backend.main:app --host 0.0.0.0 --port \"${PORT:-10000}\""]
