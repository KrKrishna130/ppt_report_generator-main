"""OpenAI-compatible LLM client with bounded concurrency and OpenTelemetry spans."""
import asyncio
import json
import time

import httpx
from opentelemetry.trace import Status, StatusCode

from app.config import settings
from app.telemetry import get_tracer, record_llm_request

_llm_semaphore = asyncio.Semaphore(max(1, settings.llm_concurrency))


def parse_json(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    start, end = raw.find("{"), raw.rfind("}")
    return json.loads(raw[start:end + 1] if start >= 0 and end > start else raw)


async def chat(role, system, prompt, temperature=0.1, max_tokens=None, image_data_url=None):
    if role == "glm":
        base, key, model = settings.glm_base_url, settings.glm_api_key, settings.glm_model
    else:
        base, key, model = settings.gemma_base_url, settings.gemma_api_key, (
            settings.gemma_vision_model if role == "vision" else settings.gemma_model
        )

    content = prompt
    if image_data_url:
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        "temperature": temperature,
        "max_tokens": max_tokens or settings.builder_max_tokens,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    error = None
    started = time.perf_counter()
    success = False

    with get_tracer().start_as_current_span("llm.chat") as span:
        span.set_attribute("llm.role", str(role))
        span.set_attribute("llm.model", str(model))
        span.set_attribute("llm.provider_endpoint", base.rstrip("/"))
        try:
            for attempt in range(settings.llm_retries + 1):
                try:
                    async with _llm_semaphore:
                        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                            response = await client.post(
                                base.rstrip("/") + "/chat/completions", json=body, headers=headers
                            )
                            response.raise_for_status()
                            payload = response.json()
                            result = payload["choices"][0]["message"]["content"]
                            success = True
                            return result
                except Exception as exc:
                    error = exc
                    if attempt < settings.llm_retries:
                        await asyncio.sleep(attempt + 1)
            span.set_status(Status(StatusCode.ERROR, "LLM request failed"))
            # Do not attach prompts, image data, response bodies, or credentials to spans.
            raise RuntimeError(f"{role} LLM request failed ({base}/{model}): {error}") from error
        except Exception:
            span.set_status(Status(StatusCode.ERROR, "LLM request failed"))
            raise
        finally:
            record_llm_request(role, model, time.perf_counter() - started, success)
