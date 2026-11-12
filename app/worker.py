"""Temporal worker entry point. Run: python -m app.worker"""
import asyncio
import logging
from temporalio.client import Client
from app.temporal.payload_codec import data_converter
from temporalio.worker import Worker
from app.config import settings
from app.temporal.workflows import PresentationWorkflow
from app.temporal import activities as activity_module
from app.services import pipeline as pipeline_module
from app.temporal.activities import reuse_cached_content, set_progress, extract_source, parse_user_prompt, resolve_settings, create_outline, build_and_validate_slide, global_review, render_outputs, regenerate_single_slide, mark_failed, complete_job, visual_qa_repair

logging.basicConfig(level=logging.INFO)

async def main() -> None:
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace, data_converter=data_converter())
    worker = Worker(client, task_queue=settings.temporal_task_queue, workflows=[PresentationWorkflow], activities=[reuse_cached_content, set_progress, extract_source, parse_user_prompt, resolve_settings, create_outline, build_and_validate_slide, global_review, render_outputs, regenerate_single_slide, mark_failed, complete_job, visual_qa_repair], max_concurrent_activities=settings.slide_concurrency + 4)
    logging.info("Temporal worker listening at %s; namespace=%s; task_queue=%s", settings.temporal_address, settings.temporal_namespace, settings.temporal_task_queue)
    try:
        await worker.run()
    finally:
        await activity_module.redis.aclose()
        if pipeline_module._digest_cache is not None:
            await pipeline_module._digest_cache.aclose()

if __name__ == "__main__":
    asyncio.run(main())
