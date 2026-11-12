# PPT Generation Pipeline

A FastAPI service for generating PowerPoint presentations from plain text or chat transcripts. The API accepts a request, creates a job, and returns a `job_id` immediately. Temporal runs the durable workflow, Redis stores job status/progress and idempotency data, and the worker uses LLMs to analyse the source, plan slides, build slide content, validate it, render the deck, and optionally run visual quality checks.

> **Important:** This README documents the intended local setup for the modified project. Exact environment-variable names and optional endpoints should match the `.env`, `docker-compose.yml`, and API schemas in the project checkout then run.

## Contents

- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Project layout](#project-layout)
- [Configure environment](#configure-environment)
- [Start locally with Docker](#start-locally-with-docker)
- [Start the API and worker without Docker](#start-the-api-and-worker-without-docker)
- [Swagger / API documentation](#swagger--api-documentation)
- [Create a presentation](#create-a-presentation)
- [Check job status and live progress](#check-job-status-and-live-progress)
- [Download generated files](#download-generated-files)
- [Regenerate a presentation](#regenerate-a-presentation)
- [Workflow stages](#workflow-stages)
- [Storage and job lifecycle](#storage-and-job-lifecycle)
- [Troubleshooting](#troubleshooting)
- [Operational notes](#operational-notes)

## Architecture

```text
Client / Swagger UI
        |
        | POST /v1/presentations
        v
FastAPI API (validate request, token/input limits, idempotency)
        |
        +----> Redis: job state, progress, idempotency, metadata
        |
        +----> local file store: large input payloads and generated artifacts
        |
        v
Temporal workflow queue
        |
        v
Temporal worker
  Stage 0: source adapter + prompt parser (parallel where possible)
  Resolver: deterministic settings and theme resolution
  Stage 1: planner / outline
  Stage 2: parallel slide builders
  Stage 3: validation and bounded retries
  Stage 4: global review
  Stage 5: PPTX rendering
  Stage 6: PDF/PNG export and visual QA (if enabled)
        |
        v
Local generated files + Redis status update + optional webhook
```

### Main components

- **FastAPI** — request validation, job submission, status endpoints, downloads and regeneration endpoints.
- **Temporal** — durable workflow execution, retries, activity timeouts and recovery after worker/process restarts.
- **Redis** — job status/progress, idempotency records and other short-lived coordination metadata. It is not the durable workflow engine.
- **Ollama + Gemma 3 4B** — local LLM for source digestion, prompt parsing, slide content and (if supported/configured) vision QA.
- **GLM-compatible endpoint** — planning and global review when configured. If the project is configured to use a different provider, set it in `.env`.
- **Renderer** — `python-pptx` creates editable PowerPoint slides and native charts.
- **LibreOffice + Poppler** — optional PDF conversion and page-to-PNG rendering for visual QA.
- **Local file storage** — generated PPTX/PDF/thumbnails and temporary input files.

## Prerequisites

Install or make available:

1. Docker Desktop and Docker Compose v2.
2. Git.
3. Ollama, if using a host-local Ollama model.
4. The configured LLM model(s), such as `gemma3:4b`.
5. Python 3.12 if running the API/worker directly on the host instead of in containers (the repository standard).

Check Docker:

```bash
docker --version
docker compose version
```

Check Ollama:

```bash
ollama --version
ollama list
```

If the model is not present:

```bash
ollama pull gemma3:4b
```

For a host-local Ollama service, check the OpenAI-compatible endpoint:

```bash
curl http://localhost:11434/api/tags
```

The default OpenAI-compatible base URL is commonly:

```text
http://localhost:11434/v1
```

When the API/worker runs **inside Docker on macOS**, `localhost` inside the container is the container itself. Use `http://host.docker.internal:11434/v1` to reach Ollama on the Mac host, unless Ollama is also running as a Compose service.

## Project layout

The exact layout can vary by revision. A typical checkout contains:

```text
ppt_generation_service/
├── app/
│   ├── main.py                 # FastAPI routes
│   ├── config.py               # Environment-backed settings
│   ├── schemas.py              # Request/response models
│   ├── services/               # Source processing, planning, validation, rendering
│   ├── temporal/
│   │   ├── workflows.py        # Temporal workflow definition
│   │   └── activities.py       # Worker activities
│   └── worker.py               # Temporal worker entry point
├── generated/                  # Final output files
├── tmp/                        # Temporary input/rendering files
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env                        # Local configuration; do not commit secrets
└── README.md
```

## Configure environment

1. Open the project directory.
2. Copy the sample environment file if the project provides one:

   ```bash
   cp .env.example .env
   ```

   If `.env.example` does not exist, create/edit `.env` using the variable names referenced by `app/config.py` and `docker-compose.yml`.
3. Review the configuration before starting services.

Common settings in this project family include:

| Setting                                               | Purpose                                                                                                                                                                    |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `OLLAMA_BASE_URL`                                   | OpenAI-compatible Ollama URL. Use `host.docker.internal` from containers on macOS.                                                                                       |
| `OLLAMA_MODEL`                                      | Local model name, e.g. `gemma3:4b`.                                                                                                                                      |
| `TEMPORAL_ADDRESS`                                  | Temporal frontend address; typically `localhost:7233` on the host and `temporal:7233` inside Compose.                                                                  |
| `TEMPORAL_NAMESPACE`                                | Temporal namespace, commonly `default`.                                                                                                                                  |
| `TEMPORAL_TASK_QUEUE`                               | Task queue listened to by the worker; must match workflow configuration.                                                                                                   |
| `REDIS_URL`                                         | Redis URL; typically `redis://localhost:6379/0` on the host and `redis://redis:6379/0` inside Compose.                                                                 |
| `OUTPUT_DIR`                                        | Directory for final PPTX/PDF/thumbnails.                                                                                                                                   |
| `TEMP_DIR`                                          | Directory for temporary inputs and rendering files.                                                                                                                        |
| `MAX_INPUT_TOKENS` / input-size limits              | Maximum accepted source size.                                                                                                                                              |
| `IDEMPOTENCY_TTL_MIN`                               | How long a request ID is treated as idempotent.                                                                                                                            |
| `JOB_TTL_HOURS`                                     | Job/status retention period.                                                                                                                                               |
| `SLIDES_MIN`, `SLIDES_MAX`, `SLIDE_CONCURRENCY` | Slide count limits and concurrent slide generation.                                                                                                                        |
| `MIN_CONTRAST`                                      | Minimum text/background contrast target.                                                                                                                                   |
| `PDF_EXPORT`, `THUMBNAILS`, `VISUAL_QA`         | Toggle optional output and QA features.                                                                                                                                    |

Use the exact variable names present in your checked-out `.env`/`app/config.py`; do not add a new variable and assume the application reads it unless code supports it. Keep credentials out of source control. If a hosted provider is used, put its API key in `.env` and do not paste it into logs or commit it.

## Start locally with Docker

Run all commands from the project root, where `docker-compose.yml` is located.

### 1. Validate Compose configuration

```bash
docker compose config
```

If this command reports an unset required variable or invalid configuration, fix `.env` or the Compose file before proceeding.

### 2. Create local output folders

```bash
mkdir -p generated tmp
```

### 3. Pull and build containers

```bash
docker compose pull temporal redis
docker compose up -d --build
```

If the Compose file uses a different service name than `temporal` or `redis`, use the names shown by:

```bash
docker compose config --services
```

### 4. Confirm services are running

```bash
docker compose ps
docker compose logs --tail=100
```

Follow logs while testing:

```bash
docker compose logs -f
```

If you need logs for one service, replace `<service>` with a service name shown by `docker compose config --services`:

```bash
docker compose logs -f <service>
```

### 5. Open the local tools

With the default port mapping described for this project:

- FastAPI Swagger UI: http://localhost:8000/docs
- FastAPI ReDoc: http://localhost:8000/redoc
- Health check: http://localhost:8000/health
- Temporal UI: http://localhost:8233
- Temporal frontend: `localhost:7233`
- Redis: `localhost:6379`

These addresses assume the Compose file publishes those ports on the host.

### 6. Stop the stack

```bash
docker compose down
```

To also remove the Compose-managed volumes, only if you intentionally want to delete persisted service data:

```bash
docker compose down -v
```

Do not use `-v` if you want to preserve Temporal/Redis volume data.

## Start the API and worker without Docker

Use this option only if your local Python environment and external services are configured.

### 1. Create and activate a virtual environment

macOS/Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Start dependencies

Ensure Redis and Temporal are already running and reachable using the host addresses in `.env`. Ensure Ollama is running and the configured model is installed.

### 3. Start the API

Use the import path that matches your application. For the common `app/main.py` layout:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Start the Temporal worker in a second terminal

Activate the same virtual environment and run the worker entry point that exists in your repository. For the common `app/worker.py` layout:

```bash
python -m app.worker
```

The API and worker are separate processes. Starting the API alone does not execute Temporal jobs.

## Swagger / API documentation

Open **http://localhost:8000/docs** after the API starts. Swagger lets you inspect request schemas, submit test payloads, view response codes, and download file responses where supported.

The service's intended endpoints are:

| Method   | Endpoint                                     | Purpose                                                                     |
| -------- | -------------------------------------------- | --------------------------------------------------------------------------- |
| `GET`  | `/health`                                  | Basic API health.                                                           |
| `GET`  | `/health/temporal`                         | Temporal connectivity, if implemented in this revision.                     |
| `POST` | `/v1/presentations`                        | Validate and enqueue a presentation job; returns HTTP `202` and a job ID. |
| `GET`  | `/v1/presentations/{job_id}`               | Read job status, current stage, progress and results when ready.            |
| `GET`  | `/v1/presentations/{job_id}/events`        | Receive progress events using Server-Sent Events (SSE), if implemented.     |
| `GET`  | `/v1/presentations/{job_id}/download.pptx` | Download the generated PowerPoint, if implemented.                          |
| `POST` | `/v1/presentations/{job_id}/regenerate`    | Regenerate the design or edit content, if implemented.                      |

The running OpenAPI document at `/openapi.json` is the source of truth for the routes implemented in the current checkout. If an optional route is not listed in Swagger, it is not available in that revision.

## Create a presentation

In Swagger:

1. Expand `POST /v1/presentations`.
2. Select **Try it out**.
3. Paste a request body like the example below.
4. Select **Execute**.
5. Copy the returned `job_id`.
6. Poll the status endpoint or subscribe to the events endpoint.
7. Download the file once the job is completed.

### Example: plain-text source

```json
{
  "request_id": "local-demo-001",
  "user_id": "demo-user",
  "prompt": "Create a professional 6-slide presentation about renewable energy. Use a green theme, include a comparison chart if the supplied source supports it, and add concise speaker notes.",
  "text": {
    "type": "plain",
    "content": "Renewable energy comes from sources that are naturally replenished. Solar power converts sunlight into electricity. Wind power uses turbines to convert wind energy into electricity. Both can reduce dependence on fossil fuels. Actual performance and cost depend on location, infrastructure, and time period."
  },
  "options": {
    "slide_count": 6,
    "language": "en",
    "theme": "green",
    "seed": 42,
    "speaker_notes": true,
    "output": ["pptx", "pdf", "thumbnails"]
  },
  "callback_url": null
}
```

Use the request schema shown in Swagger if your version differs. In particular, some revisions may use a `text` object with `content`, while chat input uses `messages`.

### Example: chat-transcript source

```json
{
  "request_id": "local-chat-demo-001",
  "user_id": "demo-user",
  "prompt": "Create a concise executive presentation with a timeline and action items. Use only information present in the transcript.",
  "text": {
    "type": "chat",
    "messages": [
      {
        "id": "m1",
        "role": "user",
        "content": "The migration starts in January. The test environment should be ready by February."
      },
      {
        "id": "m2",
        "role": "assistant",
        "content": "The team will review the test results in March. The owner for deployment is the platform team."
      }
    ]
  },
  "options": {
    "slide_count": 5,
    "language": "en",
    "theme": "blue",
    "seed": 42,
    "speaker_notes": true,
    "output": ["pptx", "pdf"]
  },
  "callback_url": null
}
```

### Example `curl` request

Save the JSON body as `request.json`, then run:

```bash
curl -sS -X POST "http://localhost:8000/v1/presentations" \
  -H "Content-Type: application/json" \
  --data-binary @request.json
```

The endpoint should return `202 Accepted` with a job ID. A successful enqueue does **not** mean the presentation is already finished.

## Check job status and live progress

Replace `<job_id>` with the ID returned by the submit endpoint.

```bash
curl -sS "http://localhost:8000/v1/presentations/<job_id>"
```

The status response may include:

- `status` — for example, queued, running, completed or failed.
- `stage` — current pipeline stage.
- `progress` — progress percentage or stage progress.
- `files` — generated artifact metadata/paths or download URLs.
- `warnings` — non-fatal issues and fallback decisions.
- `resolved_settings` — final setting values and where they came from, if exposed by the implementation.
- `timings` — stage duration data, if enabled.

### Server-Sent Events (SSE)

If the events endpoint is implemented:

```bash
curl -N "http://localhost:8000/v1/presentations/<job_id>/events"
```

`-N` disables curl buffering so progress events appear as they arrive. If the browser/client does not support SSE directly, poll the status endpoint instead.

## Download generated files

If the download endpoint is implemented, download a PowerPoint with:

```bash
curl -L "http://localhost:8000/v1/presentations/<job_id>/download.pptx" \
  -o presentation.pptx
```

PDF and thumbnail routes may vary by implementation. Check the completed job's `files` field and Swagger for the exact route. Generated files are normally written under the configured output directory (commonly `./generated`) and may also be served by a download endpoint.

The requested naming convention is:

```text
Report_<user_id>_<YYYYMMDD>_<HHMMSS>.pptx
Report_<user_id>_<YYYYMMDD>_<HHMMSS>.pdf
```

The actual filename format depends on the implementation's renderer/delivery code. Check `OUTPUT_DIR` and the job result if the filename differs.

## Regenerate a presentation

If `POST /v1/presentations/{job_id}/regenerate` is available, use Swagger to inspect its schema. A regenerate request can typically ask for a new design or a targeted slide edit. When the implementation caches the Stage 0 Content Pack, regeneration can reuse extracted facts instead of processing the source again.

Example shape only—use the schema displayed in Swagger for the exact supported fields:

```json
{
  "prompt": "Use a dark blue theme and make slide 3 more concise."
}
```

## Workflow stages

| Stage                     | Work performed                                                                                                                                                                  | Reliability measures                                                                                           |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Stage 0 — Source adapter | Cleans chat/plain text, chunks or windows input, extracts facts, numbers, dates, topics, decisions and actions. Parses explicit prompt requirements in parallel where possible. | Bounded windows/chunks, source references, retries and narrative fallback warnings.                            |
| Resolver and theme        | Resolves options from API values, explicit prompt settings, source-derived signals and config defaults. Builds a consistent palette and typography.                             | Deterministic code, recorded setting source, contrast checks and optional seed.                                |
| Stage 1 — Planner        | Creates slide outline and storyline with visual/layout diversity rules.                                                                                                         | Retry on planner failure; fail with a useful reason if retries are exhausted.                                  |
| Stage 2 — Slide builders | Builds individual slide content concurrently, using only facts relevant to each slide.                                                                                          | Semaphore/concurrency limit, guided JSON output and bounded retries.                                           |
| Stage 3 — Validation     | Checks numeric/date grounding, schema requirements and text fit.                                                                                                                | Retry failed slides; simplify a slide layout if configured retries are exhausted.                              |
| Stage 4 — Global review  | Reviews slide titles and key points for flow, repetition and terminology.                                                                                                       | Apply edits/reordering in code; redo only slides that need changes when supported.                             |
| Stage 5 — Render         | Generates editable PPTX slides, tables and native charts.                                                                                                                       | Layout positions are controlled by code/templates rather than model-generated coordinates.                     |
| Stage 6 — Visual QA      | Converts slides to images and checks for overflow, overlap, empty space, contrast and chart legibility when enabled.                                                            | Limited QA rounds and targeted fixes; non-critical QA failures should be reported as warnings where supported. |
| Delivery                  | Saves artifacts, updates job state and optionally calls a webhook.                                                                                                              | File expiry/retention, webhook retry/backoff and job status reporting when configured.                         |

The exact stage names and progress values shown to clients depend on the workflow code in the checked-out revision.

## Storage and job lifecycle

- **Redis:** short-lived job status/progress, idempotency records and coordination metadata. Redis is not a replacement for Temporal's durable workflow history.
- **Temporal:** workflow execution state, activity scheduling and retry/recovery.
- **`generated/` or `OUTPUT_DIR`:** final PPTX, PDF and thumbnails.
- **`tmp/` or `TEMP_DIR`:** intermediate inputs, rendered images and temporary conversion files.
- **Large inputs:** the API may save large payloads to local storage and pass a reference through the workflow rather than copying the entire text into the queue.
- **Expiry:** job metadata and generated files may have different TTLs; set the corresponding environment variables and confirm cleanup behavior in the implementation.
- **Idempotency:** repeated submissions with the same `request_id` within the configured idempotency window should return the existing job rather than starting duplicate work, if enabled.

Back up any generated files you need to keep. Do not assume local output folders are shared across machines or containers unless they are mounted as Compose volumes.

## Troubleshooting

### API does not start

```bash
docker compose ps
docker compose logs --tail=200
```

Check that port `8000` is free and that the `.env` file is valid. For host execution, confirm the virtual environment is activated and dependencies installed.

### Port is already allocated

Find the process/container using the port:

```bash
docker ps
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:6379 -sTCP:LISTEN
lsof -nP -iTCP:7233 -sTCP:LISTEN
```

Stop only the conflicting service you have identified. For example, if an unrelated Docker container owns port 6379, stop that container only if it is safe to do so:

```bash
docker stop <conflicting-container-name>
```

Avoid blindly stopping a container by name; it may belong to another project.

### Ollama connection refused / model not found

1. Confirm Ollama is running.
2. Confirm the model is installed using `ollama list`.
3. Check `OLLAMA_MODEL` spelling.
4. If the app runs in Docker on macOS, use `host.docker.internal` instead of `127.0.0.1` in the container's Ollama URL.
5. Inspect the API/worker logs for the exact provider URL and error.

### Job remains queued

- Confirm the Temporal worker container/process is running.
- Confirm API and worker use the same Temporal address, namespace and task queue.
- Check Temporal UI at http://localhost:8233.
- Inspect worker logs and Temporal activity failures.

### Job fails during an activity

```bash
docker compose logs --tail=300 <worker-service-name>
To check all logs--->
docker compose logs -f api worker temporal
```

Open the failed workflow in Temporal UI. Read the first underlying exception in the activity failure, not just the final workflow failure message. Correct the cause, then submit a new request or use the supported regeneration path.

### PDF or thumbnails are missing

- Confirm the request's `options.output` includes the desired output.
- Confirm LibreOffice and Poppler are installed in the worker image if the workflow uses them.
- Check write permissions for `generated/` and `tmp/`.
- Check disk space and conversion logs.
- Visual QA may be disabled by configuration; that should not prevent PPTX creation unless the implementation requires QA to pass.

### Request rejected for input size

The service may enforce character and/or token limits. Shorten the input, remove duplicated transcript turns, or adjust the appropriate supported `.env` limits. Keep limits conservative because large contexts increase memory usage and inference time.

### Duplicate requests

Use a unique `request_id` for a genuinely new job. Reusing the same ID inside the idempotency window is expected to return the existing job when idempotency is enabled.

## Operational notes

- Keep `.env` and provider credentials out of Git. Add `.env` to `.gitignore`.
- Do not expose Redis or Temporal ports to an untrusted network without access controls.
- Start with low model concurrency for local inference; increase it only after measuring RAM, VRAM and response latency.
- Configure activity timeouts and retries to match the slowest expected local model call.
- Treat source text as data, not as instructions that can override the API prompt or system policy.
- Validate all model-generated JSON and verify factual numbers/dates against the supplied source before rendering.
- A `202 Accepted` response confirms that the job was accepted, not that the PPTX/PDF succeeded.
- The `/openapi.json` document and current Swagger UI are authoritative if this README and the code differ.

## Quick-start checklist

- [ ] Docker Desktop is running.
- [ ] `.env` is configured.
- [ ] Ollama is running and the configured model is downloaded (if using local Ollama).
- [ ] `docker compose config` succeeds.
- [ ] `docker compose up -d --build` succeeds.
- [ ] `docker compose ps` shows required services running.
- [ ] `http://localhost:8000/health` responds successfully.
- [ ] `http://localhost:8000/docs` opens.
- [ ] Temporal UI opens at `http://localhost:8233`.
- [ ] A test request returns `202` and a `job_id`.
- [ ] The job reaches a terminal state and expected files appear in the output directory.

# ============User Interface(UI) PPT Generation ================

A UI made on React Js Frame work for generating PowerPoint presentations from plain text or chat transcripts. The API accepts a request, creates a job, and returns a `job_id` immediately. Temporal runs the durable workflow, Redis stores job status/progress and idempotency data, and the worker uses LLMs to analyse the source, plan slides, build slide content, validate it, render the deck, and optionally run visual quality checks.

> **Important:**
> `Install all node packages` for React Library set Up.

## Contents

- 1.Check NPM:-> npm -version
- 2.Goto directory: cd ppt_api_dashboard
- 3.Check File=package.json have or not: ls -la
- 4.Run React: npm run dev

## ============TEST APP BY UI================

- 1.Check on Browser -> http://localhost:5173/
- 2.Got To Below PPT Geneartor page -> Overview show all DashBoard
- 3.Create Represenation -> Put all details then click on Generate Representations
- 4.Go to Job Monitor -> see actuall status of current ongoing Api
- 5.Regenerate -> Go to this Menu and modify or edit ppt slides

### ============Health Test================

- Goto -> Backend connection:
- 1.API settings ->/health test this api
- 2.PI settings ->/health/temporal test this temporal works
- Local service links:
- 1.See all local services through UI Here
