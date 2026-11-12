"""Activities executed by Temporal workers. Activities are retryable and observable."""
import asyncio
import base64
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from temporalio import activity
from redis.asyncio import Redis
from app.config import settings
from app.services import object_store
from app.services.content_cache import content_key
from app.services.pipeline import source_adapter, parse_prompt, resolve, plan, build, validate, review, PALETTES
from app.services.llm import chat, parse_json
from app.services.render import render_pptx, render_pdf, render_thumbnails
from app.telemetry import traced_activity
from app.services.theme_match import match_background

log = logging.getLogger(__name__)
redis = Redis.from_url(settings.redis_url, decode_responses=True)

def job_key(job_id: str) -> str:
    return f"pptjob:{job_id}"

@activity.defn
async def reuse_cached_content(job_id: str, request: dict) -> dict | None:
    if not settings.content_cache_enabled or request.get('_regenerate'):
        return None
    try:
        cache_key = content_key(request)
        lock_key = cache_key + ':lock'
        # A single owner generates each cache entry; other jobs wait for its content.
        while True:
            raw = await redis.get(cache_key)
            if raw:
                break
            owner = await redis.get(lock_key)
            if owner == job_id or await redis.set(lock_key, job_id, nx=True,
                    ex=settings.temporal_workflow_timeout_hours * 3600 + 300):
                return None
            await asyncio.sleep(2)
        cached = json.loads(raw)
        # Store JSON content, never another user's result/download links.
        result = await render_outputs(job_id, request, cached['resolved_settings'],
            cached['theme'], cached['outline'], cached['slides'],
            list(cached.get('warnings', [])), cached['pack'])
        result['cache_hit'] = True
        return result
    except (ValueError, KeyError, TypeError) as exc:
        log.warning('Invalid content cache ignored: %s', exc)
        return None

@activity.defn
@traced_activity("set_progress")
async def set_progress(job_id: str, stage: str, percent: int, message: str, status: str = "running") -> None:
    key = job_key(job_id)
    await redis.hset(key, mapping={"job_id": job_id, "status": status, "stage": stage, "progress": str(percent), "message": message})
    await redis.expire(key, settings.job_ttl_hours * 3600)
    await redis.publish(f"pptjob-events:{job_id}", json.dumps({"job_id": job_id, "status": status, "stage": stage, "progress": percent, "message": message}))

@activity.defn
@traced_activity("extract_source")
async def extract_source(source: dict) -> dict:
    return await source_adapter(source)

@activity.defn
@traced_activity("parse_user_prompt")
async def parse_user_prompt(prompt: str) -> dict:
    return await parse_prompt(prompt)

@activity.defn
@traced_activity("resolve_settings")
async def resolve_settings(options: dict, parsed: dict, pack: dict, prompt: str) -> dict:
    resolved, theme = resolve(options, parsed, pack, prompt)
    return {"resolved": resolved, "theme": theme}

@activity.defn
@traced_activity("create_outline")
async def create_outline(pack: dict, resolved: dict, prompt: str) -> list:
    return await plan(pack, resolved, prompt)

@activity.defn
@traced_activity("build_and_validate_slide")
async def build_and_validate_slide(slide: dict, pack: dict, prompt: str, theme: dict) -> dict:
    result = await build(slide, pack, prompt, theme)
    errors = validate(result, pack.get("source_text", ""))
    for attempt in range(settings.build_retries):
        if not errors:
            break
        result = await build(slide, pack, prompt, theme, "; ".join(errors))
        errors = validate(result, pack.get("source_text", ""))
    result["validation_errors"] = errors
    return result

@activity.defn
@traced_activity("global_review")
async def global_review(slides: list, prompt: str) -> list:
    return await review(slides, prompt)

@activity.defn
@traced_activity("render_outputs")
async def render_outputs(job_id: str, request: dict, resolved: dict, theme: dict, outline: list, slides: list, warnings: list, pack: dict | None = None) -> dict:
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%I%M%p")
    user = re.sub(r"[^A-Za-z0-9_-]", "_", request.get("user_id", "user"))[:40] or "user"
    base = settings.output_path / f"Report_{user}_{stamp}_{job_id[:8]}"
    pptx = base.with_suffix(".pptx")
    theme = dict(theme)
    previous_match = theme.pop("background_match", None)
    if settings.enable_theme_background_matching:
        try:
            match = previous_match if request.get("_regenerate") and previous_match else None
            if match is None:
                match = await asyncio.to_thread(match_background, request, pack or {})
            if match:
                theme["background_match"] = match
        except (OSError, ValueError, KeyError, TypeError):
            log.exception("Background index could not be used for job %s", job_id)
            warnings.append("Background matching was unavailable. The original theme was used.")
    await asyncio.to_thread(render_pptx, slides, theme, resolved, pptx, request.get("options", {}))
    files = {"pptx": str(pptx)}
    options = request.get("options", {})
    outputs = options.get("output", ["pptx", "pdf"])
    if "pdf" in outputs and settings.enable_pdf_export:
        try:
            files["pdf"] = str(await asyncio.to_thread(render_pdf, pptx, base.with_suffix(".pdf")))
        except Exception as exc:
            warnings.append(f"PDF export skipped: {exc}")
    if "thumbnails" in outputs and settings.enable_thumbnails:
        try:
            files["thumbnails"] = json.dumps(await asyncio.to_thread(render_thumbnails, pptx, settings.output_path, files.get("pdf")))
        except Exception as exc:
            warnings.append(f"Thumbnail export skipped: {exc}")
    pack_path = base.with_suffix(".pack.json")
    pack_path.write_text(json.dumps(pack or {}, ensure_ascii=False), encoding="utf-8")
    fallback_count = sum(1 for slide in slides if slide.get("warnings"))
    validation_error_count = sum(len(slide.get("validation_errors", [])) for slide in slides)
    quality_score = max(0.0, 100.0 - fallback_count * 10.0 - validation_error_count * 8.0)
    quality = {
        "score": round(quality_score, 1),
        "fallback_slides": fallback_count,
        "validation_errors": validation_error_count,
        "slide_count": len(slides),
    }
    if quality_score < settings.min_quality_score:
        raise RuntimeError(
            f"Presentation quality score {quality_score:.1f} is below MIN_QUALITY_SCORE={settings.min_quality_score:.1f}."
        )
    manifest = {"job_id": job_id, "resolved_settings": resolved, "theme": theme,
                "outline": outline, "slides": slides, "pack_path": str(pack_path),
                "quality": quality, "warnings": warnings}
    manifest_path = base.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    files["manifest"] = str(manifest_path)
    result = {"files": files, "resolved_settings": resolved, "quality": quality, "warnings": warnings}
    if theme.get("background_match"):
        result["background_match"] = theme["background_match"]
    return result



@activity.defn
@traced_activity("regenerate_single_slide")
async def regenerate_single_slide(job_id: str, base_job_id: str, slide_id: str, request: dict) -> dict:
    """Regenerate one slide from a completed job's manifest, preserving the rest."""
    base_record = await redis.hgetall(job_key(base_job_id))
    if not base_record or base_record.get("status") != "completed":
        raise ValueError("Base presentation must exist and be completed.")
    base_result = json.loads(base_record.get("result") or "{}")
    manifest_path = base_result.get("files", {}).get("manifest")
    if not manifest_path:
        raise ValueError("Base manifest is unavailable; cannot regenerate one slide.")
    manifest = await asyncio.to_thread(object_store.read_json, manifest_path)
    slides = manifest.get("slides", [])
    outline = manifest.get("outline", [])
    pack_path = manifest.get("pack_path")
    if not pack_path:
        raise ValueError("Stored source pack is unavailable; cannot regenerate one slide.")
    pack = await asyncio.to_thread(object_store.read_json, pack_path)
    resolved = manifest.get("resolved_settings", {})
    theme = manifest.get("theme", {})
    index = next((i for i, item in enumerate(slides) if item.get("id") == slide_id), None)
    outline_item = next((item for item in outline if item.get("id") == slide_id), None)
    if index is None or outline_item is None:
        raise ValueError(f"Slide id '{slide_id}' was not found in the base presentation.")
    prompt = request.get("prompt") or ""
    instruction = request.get("_regenerate", {}).get("instruction", "")
    feedback = ("Regenerate only this slide. Preserve its original role and facts. "
                + instruction).strip()
    candidate = await build(outline_item, pack, prompt, theme, feedback)
    errors = validate(candidate, pack.get("source_text", ""))
    for _ in range(settings.build_retries):
        if not errors:
            break
        candidate = await build(outline_item, pack, prompt, theme, feedback + "; " + "; ".join(errors))
        errors = validate(candidate, pack.get("source_text", ""))
    candidate["validation_errors"] = errors
    slides[index] = candidate
    warnings = list(manifest.get("warnings", []))
    warnings.extend(errors)
    return await render_outputs(job_id, request, resolved, theme, outline, slides, warnings, pack)

async def release_content_lock(job_id):
    try:
        record = await redis.hgetall(job_key(job_id))
        request = json.loads(record.get('request') or '{}')
        lock_key = content_key(request) + ':lock'
        await redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end", 1, lock_key, job_id)
    except Exception as exc:
        log.warning('Cache lock release skipped: %s', exc)

@activity.defn
@traced_activity("mark_failed")
async def mark_failed(job_id: str, message: str) -> None:
    await release_content_lock(job_id)
    await set_progress(job_id, "failed", 100, message[:1000], "failed")

@activity.defn
@traced_activity("complete_job")
async def complete_job(job_id: str, result: dict) -> None:
    result.setdefault('cache_hit', False)
    if settings.content_cache_enabled and not result['cache_hit']:
        try:
            record = await redis.hgetall(job_key(job_id))
            request = json.loads(record.get('request') or '{}')
            if request and not request.get('_regenerate'):
                manifest = json.loads(Path(result['files']['manifest']).read_text(encoding='utf-8'))
                manifest['pack'] = json.loads(Path(manifest['pack_path']).read_text(encoding='utf-8'))
                await redis.setex(content_key(request), max(1, settings.content_cache_ttl_hours * 3600),
                                  json.dumps(manifest, ensure_ascii=False))
        except Exception as exc:
            log.warning('Content cache write skipped: %s', exc)
    # Upload after QA/cache extraction; failures prevent a false completed status.
    if not result['files']['manifest'].startswith('s3://'):
        result['files'] = await asyncio.to_thread(object_store.publish_outputs, job_id, result)
    await release_content_lock(job_id)
    key = job_key(job_id)
    await redis.hset(key, mapping={"job_id": job_id, "status": "completed", "stage": "completed", "progress": "100", "message": "Presentation files are ready", "result": json.dumps(result, ensure_ascii=False)})
    await redis.expire(key, settings.job_ttl_hours * 3600)
    await redis.publish(f"pptjob-events:{job_id}", json.dumps({"job_id": job_id, "status": "completed", "stage": "completed", "progress": 100, "message": "Presentation files are ready", "result": result}))

@activity.defn
@traced_activity("visual_qa_repair")
async def visual_qa_repair(job_id: str, request: dict, resolved: dict, theme: dict, outline: list, slides: list, pack: dict, result: dict) -> dict:
    """Optional single-round screenshot QA. Vision failures are warnings, not job-fatal."""
    if not settings.enable_visual_qa:
        result.setdefault("warnings", []).append("Visual QA disabled (ENABLE_VISUAL_QA=false)")
        return {"result": result, "slides": slides}
    pptx = Path(result["files"]["pptx"])
    theme = dict(theme)
    theme.pop("background_match", None)
    if result.get("background_match"):
        theme["background_match"] = result["background_match"]
    try:
        thumbnails = await asyncio.to_thread(render_thumbnails, pptx, settings.temp_path, result.get("files", {}).get("pdf"))
        issues = []
        for idx, image_path in enumerate(thumbnails[:len(slides)]):
            raw = Path(image_path).read_bytes()
            data_url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
            prompt = ("Inspect this presentation slide screenshot for visible text overflow, clipped elements, unreadably small text, empty content, or poor contrast. "
                      "Return JSON only: {\\\"issues\\\":[{\\\"type\\\":\\\"overflow|empty|contrast|small_text|other\\\",\\\"description\\\":\\\"short description\\\"}]}. "
                      "If no visible problem, return {\\\"issues\\\":[]}. Do not infer facts from the slide.")
            try:
                raw_answer = await chat("vision", "You are a cautious slide visual QA reviewer. Return JSON only.", prompt, max_tokens=settings.qa_max_tokens, image_data_url=data_url)
                parsed = parse_json(raw_answer)
                for issue in parsed.get("issues", [])[:3]:
                    if isinstance(issue, dict) and issue.get("description"):
                        issues.append({"index": idx, "type": str(issue.get("type", "other")), "description": str(issue["description"])[:500]})
            except Exception as exc:
                log.warning("Visual QA failed for slide %s: %s", idx + 1, exc)
        # One repair round maximum; repair only slides flagged by vision QA.
        repaired = 0
        for issue in issues:
            idx = issue["index"]
            if idx >= len(slides) or idx >= len(outline):
                continue
            feedback = f"Visual QA issue ({issue['type']}): {issue['description']}. Fix the visual/layout issue, keep facts source-grounded and text concise."
            candidate = await build(outline[idx], pack, request.get("prompt") or "", theme, feedback)
            if not validate(candidate, pack.get("source_text", "")):
                slides[idx] = candidate
                repaired += 1
        if repaired:
            await asyncio.to_thread(render_pptx, slides, theme, resolved, pptx, request.get("options", {}))
            if result.get("files", {}).get("pdf"):
                try:
                    await asyncio.to_thread(render_pdf, pptx, Path(result["files"]["pdf"]))
                except Exception as exc:
                    result.setdefault("warnings", []).append(f"PDF refresh after visual QA skipped: {exc}")
            if "thumbnails" in request.get("options", {}).get("output", []):
                try:
                    result["files"]["thumbnails"] = json.dumps(await asyncio.to_thread(render_thumbnails, pptx, settings.output_path, result.get("files", {}).get("pdf")))
                except Exception as exc:
                    result.setdefault("warnings", []).append(f"Thumbnail refresh after visual QA skipped: {exc}")
        result.setdefault("warnings", []).append(f"Visual QA checked {min(len(thumbnails), len(slides))} slide(s), found {len(issues)} issue(s), repaired {repaired} slide(s).")
        manifest_path = result.get("files", {}).get("manifest")
        if manifest_path:
            manifest = {"job_id": job_id, "resolved_settings": resolved, "theme": theme,
                        "outline": outline, "slides": slides,
                        "pack_path": str(pptx.with_suffix(".pack.json")),
                        "quality": result.get("quality", {}),
                        "warnings": result.get("warnings", [])}
            Path(manifest_path).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"result": result, "slides": slides}
    except Exception as exc:
        log.exception("Visual QA stage failed for job %s", job_id)
        result.setdefault("warnings", []).append(f"Visual QA skipped after error: {exc}")
        return {"result": result, "slides": slides}
