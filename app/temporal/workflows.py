"""Durable Temporal workflow: stages are persisted and activity retries survive worker restarts."""
from datetime import timedelta
import asyncio
from temporalio import workflow
from temporalio.common import RetryPolicy
with workflow.unsafe.imports_passed_through():
    from app.temporal.activities import reuse_cached_content, set_progress, extract_source, parse_user_prompt, resolve_settings, create_outline, build_and_validate_slide, global_review, render_outputs, regenerate_single_slide, mark_failed, complete_job, visual_qa_repair

ACTIVITY_TIMEOUT = timedelta(minutes=20)
DEFAULT_RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2.0, maximum_interval=timedelta(seconds=30), maximum_attempts=3)

@workflow.defn
class PresentationWorkflow:
    @workflow.run
    async def run(self, job_id: str, request: dict) -> dict:
        prompt = request.get("prompt") or ""
        source = request.get("text") or {}
        if workflow.patched("reference-design-v2"):
            source = dict(source)
            source["_content_mode"] = request.get("options", {}).get("content_mode", "source")
            source["_query"] = prompt or source.get("content", "")
        try:
            regeneration = request.get("_regenerate")
            if regeneration and regeneration.get("slide_id"):
                await workflow.execute_activity(set_progress, args=[job_id, "regenerate_slide", 20, "Regenerating one slide"], start_to_close_timeout=timedelta(seconds=30), retry_policy=DEFAULT_RETRY)
                result = await workflow.execute_activity(
                    regenerate_single_slide,
                    args=[job_id, regeneration.get("base_job_id"), regeneration.get("slide_id"), request],
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=DEFAULT_RETRY,
                )
                await workflow.execute_activity(complete_job, args=[job_id, result], start_to_close_timeout=timedelta(minutes=5), retry_policy=DEFAULT_RETRY)
                return result
            if workflow.patched("content-cache-v3") and not regeneration:
                cached = await workflow.execute_activity(reuse_cached_content, args=[job_id, request],
                    start_to_close_timeout=timedelta(hours=2), retry_policy=DEFAULT_RETRY)
                if cached is not None:
                    await workflow.execute_activity(complete_job, args=[job_id, cached],
                        start_to_close_timeout=timedelta(minutes=5), retry_policy=DEFAULT_RETRY)
                    return cached
            await workflow.execute_activity(set_progress, args=[job_id, "source_adapter", 5, "Extracting source facts"], start_to_close_timeout=timedelta(seconds=30), retry_policy=DEFAULT_RETRY)
            # Independent Stage 0 operations are deliberately concurrent.
            pack, parsed = await asyncio.gather(
                workflow.execute_activity(extract_source, source, start_to_close_timeout=ACTIVITY_TIMEOUT, retry_policy=DEFAULT_RETRY),
                workflow.execute_activity(parse_user_prompt, prompt, start_to_close_timeout=ACTIVITY_TIMEOUT, retry_policy=DEFAULT_RETRY),
            )
            await workflow.execute_activity(set_progress, args=[job_id, "resolver", 15, "Resolving theme and slide settings"], start_to_close_timeout=timedelta(seconds=30), retry_policy=DEFAULT_RETRY)
            resolved_bundle = await workflow.execute_activity(resolve_settings, args=[request.get("options", {}), parsed, pack, prompt], start_to_close_timeout=ACTIVITY_TIMEOUT, retry_policy=DEFAULT_RETRY)
            resolved, theme = resolved_bundle["resolved"], resolved_bundle["theme"]
            await workflow.execute_activity(set_progress, args=[job_id, "planner", 25, "Creating slide outline"], start_to_close_timeout=timedelta(seconds=30), retry_policy=DEFAULT_RETRY)
            outline = await workflow.execute_activity(create_outline, args=[pack, resolved, prompt], start_to_close_timeout=ACTIVITY_TIMEOUT, retry_policy=DEFAULT_RETRY)
            await workflow.execute_activity(set_progress, args=[job_id, "slide_builders", 30, f"Building {len(outline)} slides in parallel"], start_to_close_timeout=timedelta(seconds=30), retry_policy=DEFAULT_RETRY)
            if workflow.patched("minio-bounded-fanout-v1"):
                slides = []
                for offset in range(0, len(outline), 20):
                    batch = outline[offset:offset + 20]
                    slides.extend(await asyncio.gather(*[
                        workflow.execute_activity(build_and_validate_slide, args=[slide, pack, prompt, theme],
                            start_to_close_timeout=ACTIVITY_TIMEOUT, retry_policy=DEFAULT_RETRY)
                        for slide in batch]))
            else:
                slide_tasks = [workflow.execute_activity(build_and_validate_slide, args=[slide, pack, prompt, theme], start_to_close_timeout=ACTIVITY_TIMEOUT, retry_policy=DEFAULT_RETRY) for slide in outline]
                slides = await asyncio.gather(*slide_tasks)
            await workflow.execute_activity(set_progress, args=[job_id, "validate", 65, "Slide validation and targeted retries finished"], start_to_close_timeout=timedelta(seconds=30), retry_policy=DEFAULT_RETRY)
            slides = await workflow.execute_activity(global_review, args=[slides, prompt], start_to_close_timeout=ACTIVITY_TIMEOUT, retry_policy=DEFAULT_RETRY)
            await workflow.execute_activity(set_progress, args=[job_id, "global_review", 75, "Global consistency review finished"], start_to_close_timeout=timedelta(seconds=30), retry_policy=DEFAULT_RETRY)
            result = await workflow.execute_activity(render_outputs, args=[job_id, request, resolved, theme, outline, slides, pack.get("warnings", []), pack], start_to_close_timeout=ACTIVITY_TIMEOUT, retry_policy=DEFAULT_RETRY)
            await workflow.execute_activity(set_progress, args=[job_id, "visual_qa", 92, "Running optional visual QA"], start_to_close_timeout=timedelta(seconds=30), retry_policy=DEFAULT_RETRY)
            qa_result = await workflow.execute_activity(visual_qa_repair, args=[job_id, request, resolved, theme, outline, slides, pack, result], start_to_close_timeout=ACTIVITY_TIMEOUT, retry_policy=DEFAULT_RETRY)
            result = qa_result["result"]
            await workflow.execute_activity(complete_job, args=[job_id, result], start_to_close_timeout=timedelta(minutes=5), retry_policy=DEFAULT_RETRY)
            return result
        except Exception as exc:
            try:
                await workflow.execute_activity(mark_failed, args=[job_id, str(exc)], start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=1))
            except Exception:
                pass
            raise
