# Kirana Voice Khata

Kirana Voice Khata is a Telugu-friendly voice and text ledger demonstration.
It is a challenge prototype, **not a production financial application**. Use
fictional demo customers and transactions only. Do not enter real customer,
business, or financial information.

The application uses Gemini for extraction and external speech services for
voice transcription and speech generation. Requests can consume paid provider
credits. Protect demo access credentials, monitor provider usage, and disable or
rotate credentials when the demonstration is not in use.

## Local development

Install the Python dependencies from `requirements.txt`. FFmpeg must be
available on `PATH` to convert WebM/MP4 recordings. Run the API from the
repository root:

```powershell
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8000` by default. Set
`KVK_BACKEND_URL` only when the local backend listens elsewhere.

## Deploying the Gani AI Challenge Demo on Render

### Prerequisites

- A GitHub repository containing the project source.
- A Render account with access to create a Docker Web Service and attach a
  persistent disk. Render persistent disks require a paid service plan.
- Provider credentials configured directly in the Render dashboard.
- A fictional demo username and password to share only with intended
  evaluators.

### Prepare the GitHub repository

Review `git status` before staging. Include the Dockerfile, `.dockerignore`,
`render.yaml`, README, backend, frontend source including its package lockfile,
prompt, and tests. Do **not** add `.env`, a local SQLite database, audio
recordings, voice logs, `.venv`, `node_modules`, or generated local artifacts.
The deployment image builds the frontend from tracked source; it does not use a
local `frontend/dist`.

### Docker build overview

The multi-stage Dockerfile uses Node.js 22 to run `npm ci` and `npm run build`
inside `frontend/`. The Python 3.12 runtime installs the existing Python
requirements and FFmpeg, then copies the backend, prompt, and generated
`frontend/dist`. It runs as a non-root user. `.dockerignore` excludes secrets,
local data, recordings, logs, development dependencies, and test artifacts.

### Create the Render Web Service

1. In Render, choose **New → Blueprint** and connect the GitHub repository, or
   create a Docker Web Service using the repository root as the Docker context.
2. The included `render.yaml` configures a Docker Web Service, `/health`
   health-check path, `/var/data` persistent disk, demo authentication, and
   secret environment-variable prompts. Review the selected plan and disk cost
   in Render before creating the service.
3. If configuring the service manually, use the repository root Dockerfile.
   The container's start command is:

   ```sh
   uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-10000}"
   ```

   Render supplies `PORT`; the container command honors it.
4. Configure the environment variables below in Render. Do not place values in
   GitHub, `render.yaml`, this README, or the Dockerfile.

### Environment variables

Required for the Render demo:

- `GEMINI_API_KEY`
- `PRISMA_API_KEY`
- `TIMBRE_API_KEY`
- `DATABASE_PATH` — set to `/var/data/kirana.db`
- `DEMO_AUTH_REQUIRED` — set to `true`
- `DEMO_USERNAME`
- `DEMO_PASSWORD`

Optional provider endpoint overrides supported by the existing application:

- `PRISMA_BASE_URL`
- `TIMBRE_BASE_URL`

The provider endpoint defaults remain in the application; only override them
when the provider has supplied a different endpoint. Render sets `PORT`
automatically. Never place API keys or demo passwords in frontend code.

### Persistent disk and database

The Blueprint mounts a 1 GB disk at `/var/data` and sets
`DATABASE_PATH=/var/data/kirana.db`. The app creates the directory if needed
and initializes an empty database on first startup. It does not import the
developer's local `data/kirana.db`. Keep a separate backup before any database
migration or restore operation; verify the backup can be restored before
relying on it.

SQLite on this disk is intended only for one Render service instance. Do not
scale this demo horizontally or run multiple service instances against the same
SQLite file. Render disks are attached to a single instance and can affect
deployment availability.

### Deploy and verify

After configuration, deploy from Render. Check the build and startup logs
without copying secrets into support messages. Verify:

1. `https://<your-service>.onrender.com/health` returns
   `{"status":"ok"}`.
2. The root URL shows the built frontend. The browser may prompt for the
   configured demo username/password.
3. Once authenticated, verify a fictional customer list/ledger loads and the
   voice/text interaction works. Confirm a transaction is only written after
   explicitly confirming its pending transaction.
4. An unknown `/api/...` path returns a JSON 404, not the frontend HTML.

The `/health` endpoint is intentionally unauthenticated and reports only
application liveness. Other routes, including static frontend files and all
customer/ledger/provider operations, require HTTP Basic demo credentials when
`DEMO_AUTH_REQUIRED=true`.

The backend also detects Render's `RENDER=true` environment variable and
requires demo authentication there even if `DEMO_AUTH_REQUIRED` is absent or
set to `false`. In local development, authentication remains disabled by
default unless `DEMO_AUTH_REQUIRED=true`.

### Browser authentication acceptance (manual)

The frontend's Node tests verify that voice multipart requests, JSON requests,
confirmation, cancellation, and 401 error handling use the shared same-origin
API adapter. They do **not** exercise browser HTTP Basic credential caching.
Before sharing the demo, verify this in a fresh private/incognito browser
window:

1. Open `/health`; verify it returns the health JSON without an authentication
   prompt.
2. Open the service root. Verify the browser prompts for HTTP Basic
   credentials; reject or cancel once and confirm the protected app does not
   load. Reopen it and sign in with the configured demo credentials.
3. Open Developer Tools → Network and enable **Preserve log**. Load the app;
   verify customer/summary requests succeed and do not return 401.
4. Record a short fictional voice request. Verify the multipart
   `POST /api/voice` succeeds, then complete a confirmation/cancellation flow.
   Verify JSON `POST /api/text`, `POST /api/confirm/{pending_id}`, and
   `POST /api/cancel/{pending_id}` succeed after browser authentication.
5. In Network request details, confirm requests are same-origin and have no
   401 responses after login. Do not copy, screenshot, or share the
   `Authorization` header or any credential value.

### Protect Gani AI provider credits

- Keep the demo username/password private and share them only with intended
  evaluators.
- Use fictional data only; the app is not suitable for real financial records.
- Limit the demo window and rotate the credentials and provider keys afterward.
- Monitor provider usage and set any available provider-side spend/usage limits.
- Do not embed provider keys in the browser or ask participants to supply keys.
- Disable the service or remove provider credentials when the challenge demo
  is no longer needed.

Authentication reduces casual public abuse but does not impose per-user quotas.
Anyone given the credentials can make requests until the service is disabled
or provider-side limits are reached.

### Troubleshooting

- **FFmpeg unavailable / audio conversion fails:** verify the Docker image
  installs `ffmpeg` and rebuild it. WAV uploads do not require conversion;
  WebM/MP4 conversion does.
- **Provider is not configured:** verify the required key *names* are present
  in Render's environment settings. Never paste key values into logs or
  support chats.
- **Demo auth is not configured:** set `DEMO_AUTH_REQUIRED=true` and provide
  both `DEMO_USERNAME` and `DEMO_PASSWORD`. If auth is required but either is
  absent, protected routes return a configuration error rather than becoming
  public.
- **Database cannot open:** confirm the persistent disk is mounted at
  `/var/data`, `DATABASE_PATH` is `/var/data/kirana.db`, and the service can
  write there. Do not copy a developer database into the image.
- **Frontend missing/build failure:** check that `frontend/package-lock.json`
  is tracked and `npm ci`/`npm run build` succeeded in the Docker build stage.
  The runtime expects `frontend/dist/index.html`.
- **Render health check fails:** inspect container startup logs and verify the
  service starts with the Dockerfile command and Render-provided `PORT`.

## Safety and scope

The service provides no user-level roles or per-user data separation. HTTP
Basic credentials are a lightweight gate for a limited challenge demo, not
production-grade authentication. Use fictional demo records only; never use
this prototype as a live customer ledger or source of truth.
