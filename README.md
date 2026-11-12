# ppt_report_generator

Turns a prompt and source text into a finished PowerPoint deck (and PDF): a FastAPI API and a Temporal worker
that outline the deck, build each slide with an LLM, validate it against the source, and render PPTX and PDF.

## Python

The app's Docker image is based on `python:3.11-slim`. For host runs, use a Python 3.11 or 3.12 virtual
environment or conda env (both run the app).

## Quick start

Follow [PPT_Backend_Guide.md](PPT_Backend_Guide.md): Redis and Temporal from `docker-compose.yml`, then the API
and worker. A sample request is in [Payload_ppt.txt](Payload_ppt.txt).

## Repository layout

```text
app/                     PPT generator (FastAPI API, Temporal workflow and activities, services)
ppt_api_dashboard/       web dashboard for the API
docker-compose.yml       Redis, Temporal, API and worker
PPT_Backend_Guide.md     full guide to the PPT generator
Payload_ppt.txt          sample API request
```

## Troubleshooting

- **Every slide comes out as a fallback and the logs say `Unknown scheme for proxy URL 'socks://...'`:** the
  shell has a SOCKS `ALL_PROXY` set, which the app's HTTP client rejects even for local LLM calls. Unset
  `ALL_PROXY` / `all_proxy` for the API and worker.
- **A job fails with `Presentation quality score ... is below MIN_QUALITY_SCORE`:** the app's validator found
  numbers that are not in the source (common with small local models). Use a stronger model, or lower
  `MIN_QUALITY_SCORE` for testing only.

## Automatic presentation backgrounds

The supplied `.env` enables automatic matching. Set
`ENABLE_THEME_BACKGROUND_MATCHING=false` to use the original rendering path.
After changing the setting, recreate the worker and API containers.

```bash
docker compose up -d --build
```

Submit the same request body as before. The matcher uses the API prompt,
plain or chat source content, and the source digest already produced by the
pipeline. Studio's **Describe your deck** and **Additional details** are
included through those existing request fields.

- `app/assets/PPT_Theme_Backgrounds_JPEGs/` contains all 96 original JPEGs
  in their 24 folders, an editable `catalog.csv`, and `vectors.json`.
- Each image vector encodes its catalog category and a caption written after
  visual inspection. The query uses the same vocabulary and exists only in
  memory during matching. The implementation uses cosine similarity and
  requires no additional model, API call, database, or credential.
- The highest-scoring positive match supplies the deck background. The design
  applies a tinted version behind editable slide content and uses the original
  image in the designed cover's photo panel. Existing layouts and palettes
  are retained except for the matched cover composition.
- If there is no vocabulary overlap, the original theme is used. The catalog
  uses English descriptions, so matching works best with English input or an
  English source digest.
- The status response and exported manifest include `background_match` when
  selected, with the image path, category, and cosine score. Redis content
  cache hits still apply the worker's current flag when exporting. Submit a
  new request ID to generate a fresh export after switching the flag.

After editing captions or category terms, rebuild the vector index from the
project root and rebuild the worker image.

```bash
python -m app.services.theme_match
docker compose up -d --build
```
