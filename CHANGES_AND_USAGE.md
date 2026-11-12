# Prompt settings and shared content caching

## Result

Priority: non-null structured option > explicit prompt instruction > domain/content inference > defaults. `slide_count: 9` beats a prompt asking for 17. With a null slide count, both “create 15 slides” and “slide 17” work. Numeric counts are clamped to the configured range (currently 4–20); unsupported requests such as 100 slides do not produce 100 slides.

The existing project already had an LLM prompt parser, setting resolver, request-ID idempotency, and a source digest cache. The changes add reliable numeric instruction extraction, fix automatic design overwriting requested colors, and add reuse of completed slide content before expensive generation stages.

## Files changed

| File | Change |
|---|---|
| app/schemas.py | Nullable design_theme, content_mode, speaker_notes. Missing/null content_mode selects source when text is supplied, topic otherwise. Notes follow explicit prompt intent, default true. |
| app/services/intent.py | New deterministic numeric slide/count and color/notes instruction extraction; domain color rules. |
| app/services/pipeline.py | Explicit prompt instructions override LLM parser guesses; options still win. Domain palettes; custom colors survive automatic design selection. |
| app/services/content_cache.py | New SHA-256 content identity, independent of user_id/request_id/callback_url. Includes prompt, text, options, model names and generation settings. |
| app/temporal/activities.py | Redis shared-content lookup, generation lock, new exports from cached slides, cache write after completion, lock cleanup. |
| app/temporal/workflows.py | Versioned cache check before extraction/parsing/planning/building/review. Cache hits jump to export and completion. |
| app/worker.py | Register new cache activity. |
| app/config.py, .env, .env.example | CONTENT_CACHE_ENABLED=true; CONTENT_CACHE_TTL_HOURS=168. |
| docker-compose.yml | Redis AOF persistence on existing redis_data volume. |
| ppt_api_dashboard/src/AIStudio.jsx, src/main.jsx | Automatic slide count choice sends null; default is automatic. |
| tests/test_intent_cache.py | Options, domain colors, parser conflict, cache identity/reuse/concurrency, real 17-slide PPTX export tests. |
| tests/test_design_system.py | Update old test to expect automatic topic mode for prompt-only input. |

## Domain palettes

| Subject | Automatic accent |
|---|---|
| Terrorism, danger, emergency | Crimson #B91C3C |
| Bank, finance, corporate, authority | Navy #142D4E |
| Act, constitution, legal | Burgundy #800020 |
| Cybersecurity | Electric blue #38BDF8 on dark background |
| Environment | Forest green #166534 |
| Water | Teal #0F766E |
| Education | Navy #142D4E |

Explicit color instructions such as “color is Red” override these rules. Structured theme/brand colors remain supported. A specifically selected design_theme intentionally chooses that named design; leave it auto/null for prompt/domain color selection. These are keyword heuristics, not a complete semantic classifier. Domain themes use a neutral background with the requested accent, rather than painting all text/background red.

## Example request

```json
{
  "request_id": "256323",
  "user_id": "studio-user",
  "prompt": "Create a presentation on the History of Terrorism in India, color is Red and slide 17. Include speaker notes.",
  "text": null,
  "callback_url": null,
  "options": {
    "design_theme": null,
    "content_mode": null,
    "slide_count": null,
    "language": null,
    "theme": null,
    "theme_style": null,
    "seed": null,
    "font": null,
    "brand_colors": null,
    "style": null,
    "template": null,
    "speaker_notes": null,
    "output": ["pptx", "pdf"]
  }
}
```

This resolves to 17 slides, red accent, topic mode, and enabled notes. “Without speaker notes” disables notes when the notes field is null. Explicit false always wins. With text supplied, automatic content mode uses that source; without text it drafts from the topic. Explicit source mode still requires source text. Null design_theme behaves as auto.

## Cache behavior

First request: acquire shared generation lock → generate content → export → cache completed slide data. Second identical request after one hour, under any user/request ID: load Redis content → render fresh PPTX/PDF → complete. A concurrent matching request waits for the owner and then exports cached content. The result includes `cache_hit: true` for a hit, false for new generation. Poll the existing status endpoint to read it under result.

The cache stores source pack, resolved settings, theme, outline and completed slides. It does not return another user's download URLs. Output files have a new job ID and caller-specific filename. The default reuse window is seven days from initial cache creation; hits do not extend it. Redis eviction, cache expiry, changed inputs/options/models, or disabled caching trigger generation. Output formats are included in cache identity. Explicit seeds also affect identity; null seed reuses the first completed design. Existing pre-upgrade presentations are not automatically imported into this new cache.

Only request/user identifiers and callback URL are excluded: same prompt with different source material/options is a different cache entry. Global sharing of identical source input is intentional as requested. This project still has no authentication or job ownership enforcement; caller-provided user_id is not an access-control boundary.

The generation lock expires after the configured workflow timeout plus five minutes if a process dies. Explicit failures release it. The regenerate endpoint bypasses the shared cache to preserve regeneration behavior. The pre-existing same-user/same-request-ID replay still returns its original job; use a fresh request_id for a new API submission. Cache reuse skips AI generation, but export still takes time and the API remains asynchronous (202).

## Start

Extract the ZIP and run in its ppt_generation_service directory:

```bash
docker compose up -d --build
```

Frontend: http://localhost:5173
API docs: http://localhost:8000/docs

Keep your Gemma/Ollama endpoint available as before. PDF export requires the image's LibreOffice installation. Existing host port conflicts must be resolved before Compose can start. Do not delete redis_data if you want to retain cached content.

## Validation

Run `python -m pytest -q` and `python -m compileall -q app`. Tests use mocked LLM/Redis where appropriate and include opening a rendered 17-slide PowerPoint. Live Gemma, Redis/Temporal cluster execution and PDF conversion require your running services and have not been verified in this environment.

The deliverable retains the application, frontend, deployment files, reference assets, documentation and configuration. Git history, macOS metadata, build/dependency caches, and old generated/example output files are omitted.
