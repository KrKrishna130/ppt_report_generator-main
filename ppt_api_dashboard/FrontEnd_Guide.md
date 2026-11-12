# DeckFlow — PPT Generation API Dashboard

A responsive React + Vite UI for locally testing the existing FastAPI PPT generation service.

## Features
- Health checks for `/health` and `/health/temporal`
- Form builder and JSON preview for `POST /v1/presentations`
- Job status refresh and SSE event stream
- PPTX/PDF downloads
- Single-slide or full-deck regeneration
- Request history, API URL settings, Swagger/ReDoc links

## Requirements
- Node.js 18+ (20 LTS recommended)
- npm
- Your FastAPI backend running (default `http://localhost:8000`)

## Run locally
In Terminal:

```bash
cd ppt_api_dashboard
npm install
npm run dev
```

Open `http://localhost:5173`.

## Start the backend separately
Use your backend project's existing startup instructions. For a Docker Compose setup, typically:

```bash
docker compose up -d --build
docker compose ps
```

Useful URLs:
- API health: `http://localhost:8000/health`
- Temporal health: `http://localhost:8000/health/temporal`
- Swagger: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Temporal UI (if exposed): `http://localhost:8233`

## CORS
The browser UI normally runs at `http://localhost:5173`. Ensure FastAPI CORS allows this origin (and `http://127.0.0.1:5173` if used). Restart the backend after changing CORS configuration.

## Workflow
1. Use **API settings** to set the base URL and test health.
2. Use **Create presentation** to fill request ID, user ID, prompt, source text, slide count, theme, notes, and output formats.
3. Submit and follow the job in **Job monitor**.
4. Refresh status or connect to SSE; download outputs after completion.
5. Use **Regenerate slide** with the original job ID and a slide ID such as `s2`; monitor the returned new job ID.

## API paths used
- `GET /health`
- `GET /health/temporal`
- `POST /v1/presentations`
- `GET /v1/presentations/{job_id}`
- `GET /v1/presentations/{job_id}/events`
- `GET /v1/presentations/{job_id}/download.pptx`
- `GET /v1/presentations/{job_id}/download.pdf`
- `POST /v1/presentations/{job_id}/regenerate`

Confirm exact schemas and endpoint availability in the running Swagger UI; backend versions may differ slightly. The dashboard stores the API base URL in localStorage and request logs in in-memory session state. For production, configure HTTPS, authentication, and restrictive CORS.
