# PPT Report Generator — Bugs & Enhancements to the Current Flow

_Prepared 2026-10-21. Scope: fix bugs and improve the existing pipeline. Agents and classifiers are out of scope for now._

---

## 1. Current flow

```
Client
  │ POST /v1/presentations  {text, prompt, options}
  ▼
FastAPI (app/main.py)
  ├─ idempotency check (Redis key user_id:request_id, 60 min)
  ├─ job record pptjob:{id} in Redis → status "queued"
  └─ start Temporal workflow "presentation-{id}"  ──▶ 202 {job_id, status_url, events_url}
                                │
Temporal worker (app/worker.py) → PresentationWorkflow (app/temporal/workflows.py)
  5%  extract_source  ║ parse_user_prompt     (in parallel)
        └ clean text → ~12k-char chunks → LLM digest per chunk → merged "pack"
 15%  resolve_settings   options > prompt > inferred > default; theme palette (no LLM)
 25%  create_outline     LLM plans N slides (fixed fallback outline if it fails)
 30%  build_and_validate_slide × N   (in parallel; schema check; 1 retry)
 65%  global_review      LLM edits titles and order only
 75%  render_outputs     python-pptx → PPTX; LibreOffice → PDF; pdftoppm → thumbnails; JSON manifest
 92%  visual_qa_repair   optional (off by default): vision LLM per slide, one repair round
100%  complete_job       result stored in Redis
  (any error → mark_failed)
Client ◀── GET /{id} (poll) · GET /{id}/events (SSE) · GET /{id}/download.{pptx|pdf|json}
       ◀── POST /{id}/regenerate → reruns the full workflow under a new job id
```

---

## 2. Bugs

| #     | Bug                                                                                                                                                                                                                  | Where                                 | Fix                                                                                                       |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| BUG-1 | **Dark theme makes text unreadable.** The word "dark" in the prompt selects the `dark` palette, whose text colour is `#F8FAFC`, but the slide background is never set, so the text is near-white on white. | `pipeline.py:24`, `render.py:214` | Set the slide background from the theme; add a contrast check using the existing `min_contrast` setting |
| BUG-2 | **`theme_style` is ignored.** It's resolved but the renderer never reads it.                                                                                                                                 | `pipeline.py:265`, `render.py`    | Pass it to the renderer as part of the design spec (section 3.3)                                          |
| BUG-3 | **`seed` is unused.** It's generated and saved in the manifest, but nothing uses it, so there's no reproducible variation.                                                                                   | `pipeline.py:319`                   | Use `random.Random(seed)` in `resolve_design` (section 3.3)                                           |
| BUG-4 | **`layout_variant` and `visual_type` are ignored.** Every slide is header + bullets or one chart, so there are no title, table, KPI or two-column slides.                                                  | `render.py:214`                     | Layout components (section 3.2)                                                                           |
| BUG-5 | **`validate(slide, source)` never uses `source`**, so made-up numbers and quotes get through.                                                                                                              | `pipeline.py:576`                   | Grounding check (section 3.4)                                                                             |
| BUG-6 | **`RegenerateRequest.slide_id` is unused.** Regenerate always rebuilds the whole deck.                                                                                                                       | `main.py` `regenerate`            | Regenerate a single slide (section 3.6)                                                                   |
| BUG-7 | **The SSE endpoint blocks the server's event loop:** it uses the synchronous Redis client inside an async generator.                                                                                           | `main.py` `events`                | Use `redis.asyncio`                                                                                     |
| BUG-8 | `@app.on_event("shutdown")` is deprecated.                                                                                                                                                                         | `main.py`                           | Use a `lifespan` handler                                                                                |
| BUG-9 | **Overflow is handled by cutting text** (5 bullets × 240 characters, rough line estimate).                                                                                                                    | `pipeline.py:452`, `render.py:48` | Measured text and splitting (section 3.2)                                                                 |

---

## 3. Enhancements to the current flow

### 3.1 Layout engine (`render.py`)

- **Component library, chosen by `layout_variant`:** title, agenda, section, bullets, two_column, chart, table, kpi, timeline, quote, closing.
- **Auto-add** a title slide first and a closing slide last if the outline has none.
- **Measured text:**
  - Measure with the real font metrics (Pillow `ImageFont`) instead of `estimate_lines`.
  - Shrink the font down to a minimum size, then **split onto a continuation slide** instead of truncating.
- **Brand template:** optional `.potx` master via `options.template`.
- Delete the commented-out legacy code in `render.py`.

### 3.2 Design resolver: theme, colour, font and randomness from intent

Order of precedence:

1. Explicit options (`theme`, `font`, `brand_colors`, `seed`)
2. The prompt ("dark", "minimal", "playful", hex codes, "use Arial")
3. Inferred from the text (domain family, tone and audience, returned by the digest)
4. Config defaults

```python
DESIGN_FAMILIES = {
  "corporate": {"palettes": ["navy", "slate", "teal"], "fonts": [("Inter", "Inter"), ("Source Sans 3", "Source Sans 3")],
                "backgrounds": ["light", "light_band"], "title_styles": ["left_bar", "underline"], "density": "medium"},
  "finance":   {"palettes": ["navy", "green", "graphite"], "fonts": [("IBM Plex Sans", "IBM Plex Sans")], ...},
  "creative":  {"palettes": ["purple", "coral", "sunset"], "fonts": [("Poppins", "Inter"), ("Montserrat", "Open Sans")],
                "backgrounds": ["light", "dark", "gradient"], "title_styles": ["big_center", "split"], "density": "low"},
  "technical": {"palettes": ["slate", "blue", "dark"], "fonts": [("Inter", "JetBrains Mono")], ...},
  "education": {...}, "healthcare": {...},
}

def resolve_design(intent: dict, options: dict, seed: int) -> dict:
    rng = random.Random(seed)                         # same seed → same deck
    fam = DESIGN_FAMILIES[intent.get("domain_family", "corporate")]
    palette = options.get("brand_colors") or intent.get("theme_color") or rng.choice(fam["palettes"])
    heading, body = intent.get("font") and (intent["font"], intent["font"]) or rng.choice(fam["fonts"])
    background = "dark" if intent.get("theme_style") == "dark" else rng.choice(fam["backgrounds"])
    spec = {
        "palette": build_palette(palette, background),   # text/bg/accents derived for the background
        "fonts": {"heading": heading, "body": body},
        "background": background,
        "title_style": rng.choice(fam["title_styles"]),
        "density": fam["density"],
        "layout_seed": rng.randint(0, 2**31),            # per-slide layout variation
    }
    enforce_contrast(spec, settings.min_contrast)        # fixes BUG-1
    return spec
```

- The user's explicit choices always win; the seed only fills in what wasn't specified.
- Same seed gives the same deck. `RegenerateRequest.new_seed=true` gives a fresh look with the same content.
- File changes:
  - `schemas.py`: `Options` gets `font`, `brand_colors`, `style`, `template`.
  - `parse_prompt`: also extract font, hex colours and style words.
  - Digest: return `domain_family`.
  - **`Dockerfile`: install the fonts** (Inter, Poppins, IBM Plex, Source Sans 3, ...), or LibreOffice swaps fonts in the PDF.
  - Manifest: record the design spec and the reason for each choice.

### 3.3 Grounding (no agents)

- **Digest:** each fact carries a `source_quote` / `source_span`.
- **`validate()` uses `source`:**
  - Normalise numbers on both sides (`1,200`, `1200`, `1.2k`, `12%`).
  - Flag any number or quote on the slide that isn't in the source.
  - Failures feed the existing retry in `build_and_validate_slide`.
- **Charts:** only allowed if every chart value appears in the slide's evidence; otherwise `chart = None`.

### 3.4 Deck coherence

- **Build slides in groups of 3–4** per LLM call, with neighbouring slide titles in the prompt. This cuts calls and repetition.
- **Extend `review()`:** besides `title_edits` and `order`, allow `drop` and `merge` (slide id lists), applied deterministically and within slides_min and slides_max.

### 3.5 Speed and cost

- **Store the pack once** (file under `temp_dir`, or Redis) and pass a reference to activities instead of the full source. This keeps Temporal's history small (roughly 2 MB payload limit).
- **Cache digests** by `sha256(chunk)` in Redis.
- **Merge `parse_prompt` into the digest or the plan step** to save one call.
- **One LibreOffice pass:** produce the PDF once and reuse it for thumbnails and visual QA.
- **Visual QA only on flagged slides:** slides near the overflow limit or with low contrast.
- **Regenerate one slide:**
  - Save the pack, outline and design spec per job.
  - `regenerate` with `slide_id` reruns only build, validate and render for that slide.
  - `regenerate` without `slide_id` reuses the pack and skips extraction.

### 3.6 Quality and failures

- **Quality score in the manifest:**
  - % of slides that used a fallback
  - Validation errors
  - Unsupported numbers
  - Overflow splits
- **`min_quality` setting:** below the threshold, mark the job `failed` with the reason instead of silently "completing".

### 3.7 Cleanup and ops

- **Remove dead code:**
  - `run_pipeline`
  - Commented-out blocks in `config.py`, `render.py` and `docker-compose.yml`
  - The `glm_*` and `gemma_*` settings, after 3.1
- **Server hygiene:**
  - Auth, a rate limit per `user_id`, and CORS from config.
  - Use the `lifespan` handler and async Redis (BUG-7, BUG-8).
- **Evaluation set** of 20–30 sample inputs with these metrics (run on every prompt or model change):
  - Unsupported numbers
  - Overflow or split count
  - Repeated titles
  - Fallback rate
  - Latency
- Tests for `resolve()`, `resolve_design()`, `validate()` and the renderer components.

---

## 4. Roadmap

| Phase       | Work                                                                                                           | Covers                | Effort          |
| ----------- | -------------------------------------------------------------------------------------------------------------- | --------------------- | --------------- |
| **0** | Dark-theme fix: background from theme + contrast check                                                         | BUG-1                 | Small           |
| **1** | Per-role GLM/Qwen models, schema-constrained output, LLM concurrency limit, Pydantic schemas, delete dead code | 3.1, 3.8              | Small           |
| **2** | Layout engine + design resolver (seed, fonts, intent families, fonts in Dockerfile)                            | BUG-2/3/4/9, 3.2, 3.3 | Medium          |
| **3** | Grounding in `validate()`, chart gating                                                                      | BUG-5, 3.4            | Small to medium |
| **4** | Grouped slide building, extended review                                                                        | 3.5                   | Small           |
| **5** | Pack by reference, digest cache, one LibreOffice pass, single-slide regenerate                                 | BUG-6, 3.6            | Medium          |
| **6** | Quality score and threshold, async Redis and lifespan, auth, evaluation set and tests                          | BUG-7/8, 3.7, 3.8     | Ongoing         |

_Later, only if needed: bounded agents (slide, planner, reviewer) and decision classifiers. Revisit after Phase 6 metrics show where one-shot calls fall short._
