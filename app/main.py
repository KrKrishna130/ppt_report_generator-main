"""FastAPI API. Temporal owns durable workflow execution; Redis is for status, SSE and idempotency."""
import asyncio
import json
import uuid
from pathlib import Path
from datetime import timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis
from temporalio.client import Client
from app.temporal.payload_codec import data_converter
from app.config import settings
from app.services import object_store
from minio.error import S3Error
from app.schemas import PresentationRequest, RegenerateRequest
from app.temporal.workflows import PresentationWorkflow
from app.telemetry import configure_telemetry
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

configure_telemetry("ppt-generation-api")
HTTPXClientInstrumentor().instrument()

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    global _client
    if _client is not None:
        _client = None
    await redis.aclose()

# Air-gapped bundles ship Swagger UI and ReDoc in app/static/docs (fetched at build time by
# airgap/fetch_docs_assets.sh), so /docs works without internet. Without those files, /docs and /redoc
# use FastAPI's default CDN pages.
DOCS_ASSETS = Path(__file__).parent / "static" / "docs"
LOCAL_DOCS = all((DOCS_ASSETS / f).is_file() for f in ("swagger-ui-bundle.js", "swagger-ui.css", "redoc.standalone.js"))

app = FastAPI(title=settings.app_name, version="2.2.0", lifespan=lifespan,
              **({"docs_url": None, "redoc_url": None} if LOCAL_DOCS else {}))
FastAPIInstrumentor.instrument_app(app)

if LOCAL_DOCS:
    app.mount("/static/docs", StaticFiles(directory=DOCS_ASSETS), name="docs-static")

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui():
        return get_swagger_ui_html(openapi_url=app.openapi_url, title=f"{app.title} - Swagger UI",
                                   oauth2_redirect_url="/docs/oauth2-redirect",
                                   swagger_js_url="/static/docs/swagger-ui-bundle.js",
                                   swagger_css_url="/static/docs/swagger-ui.css",
                                   swagger_favicon_url="/static/docs/favicon-32x32.png")

    @app.get("/docs/oauth2-redirect", include_in_schema=False)
    async def swagger_ui_redirect():
        return get_swagger_ui_oauth2_redirect_html()

    @app.get("/redoc", include_in_schema=False)
    async def redoc():
        return get_redoc_html(openapi_url=app.openapi_url, title=f"{app.title} - ReDoc",
                              redoc_js_url="/static/docs/redoc.standalone.js",
                              redoc_favicon_url="/static/docs/favicon-32x32.png", with_google_fonts=False)
app.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()], allow_methods=["GET", "POST"], allow_headers=["*"])
redis = Redis.from_url(settings.redis_url, decode_responses=True)
def key(job_id: str) -> str: return f"pptjob:{job_id}"
_client: Client | None = None

async def temporal_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace, data_converter=data_converter())
    return _client

@app.get("/health")
async def health():
    checks = {"redis": "ok", "temporal": "unknown", "output_dir": str(settings.output_path)}
    try: await redis.ping()
    except Exception as exc: checks["redis"] = f"error: {exc}"
    checks["status"] = "ok" if checks["redis"] == "ok" else "degraded"
    return checks

@app.get("/health/temporal")
async def temporal_health():
    try:
        client = await temporal_client()
        await client.service_client.check_health()
        return {"status": "ok", "address": settings.temporal_address, "namespace": settings.temporal_namespace, "task_queue": settings.temporal_task_queue}
    except Exception as exc:
        raise HTTPException(503, f"Temporal unavailable: {exc}") from exc

async def start_workflow(job_id: str, payload: dict) -> None:
    client = await temporal_client()
    await client.start_workflow(PresentationWorkflow.run, args=[job_id, payload], id=f"presentation-{job_id}", task_queue=settings.temporal_task_queue, execution_timeout=timedelta(hours=settings.temporal_workflow_timeout_hours))

@app.post("/v1/presentations", status_code=202)
async def create(body: PresentationRequest):
    payload = body.model_dump(mode="json")
    serial = json.dumps(payload, ensure_ascii=False)
    if len(serial) > settings.max_input_chars * 2:
        raise HTTPException(413, f"Request too large; MAX_INPUT_CHARS={settings.max_input_chars}")
    idem = f"ppt-idem:{body.user_id}:{body.request_id}"
    old = await redis.get(idem)
    if old:
        return {"job_id": old, "status": await redis.hget(key(old), "status") or "queued", "idempotent_replay": True, "status_url": f"/v1/presentations/{old}", "events_url": f"/v1/presentations/{old}/events"}
    job_id = str(uuid.uuid4())
    await redis.hset(key(job_id), mapping={"job_id": job_id, "user_id": body.user_id, "status": "queued", "stage": "queued", "progress": "0", "message": "Accepted by API", "request": serial})
    await redis.expire(key(job_id), settings.job_ttl_hours * 3600)
    try:
        await start_workflow(job_id, payload)
    except Exception as exc:
        await redis.hset(key(job_id), mapping={"status": "failed", "stage": "submission", "progress": "0", "message": f"Could not start Temporal workflow: {exc}"})
        raise HTTPException(503, f"Could not start Temporal workflow: {exc}") from exc
    await redis.setex(idem, settings.idempotency_ttl_min * 60, job_id)
    await redis.publish(f"pptjob-events:{job_id}", json.dumps({"job_id": job_id, "status": "queued", "stage": "queued", "progress": 0, "message": "Temporal workflow started"}))
    return {"job_id": job_id, "status": "queued", "status_url": f"/v1/presentations/{job_id}", "events_url": f"/v1/presentations/{job_id}/events", "workflow_id": f"presentation-{job_id}"}

@app.get("/v1/presentations/{job_id}")
async def status(job_id: str):
    d = await redis.hgetall(key(job_id))
    if not d: raise HTTPException(404, "Job not found or expired")
    return {"job_id": job_id, "status": d.get("status"), "stage": d.get("stage"), "progress": int(d.get("progress", 0)), "message": d.get("message"), "result": json.loads(d["result"]) if d.get("result") else None}

@app.get("/v1/presentations/{job_id}/events")
async def events(job_id: str):
    if not await redis.exists(key(job_id)): raise HTTPException(404, "Job not found")
    async def stream():
        ps = redis.pubsub(); await ps.subscribe(f"pptjob-events:{job_id}")
        try:
            yield "event: connected\ndata: " + json.dumps({"job_id": job_id}) + "\n\n"
            for _ in range(3600):
                msg = await ps.get_message(ignore_subscribe_messages=True, timeout=1)
                if msg and msg.get("data"): yield "data: " + msg["data"] + "\n\n"
                d = await redis.hgetall(key(job_id))
                if d.get("status") in ("completed", "failed"):
                    yield "event: terminal\ndata: " + json.dumps({"status": d["status"], "message": d.get("message")}) + "\n\n"
                    break
                await asyncio.sleep(.2)
        finally: await ps.aclose()
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/v1/presentations/{job_id}/download.{extension}")
async def download(job_id: str, extension: str):
    if extension not in {"pptx", "pdf", "json"}: raise HTTPException(400, "Supported extensions: pptx, pdf, json")
    d = await redis.hgetall(key(job_id))
    if not d: raise HTTPException(404, "Job not found")
    if d.get("status") != "completed": raise HTTPException(409, f"Job is {d.get('status', 'unknown')}; wait until completed")
    result = json.loads(d.get("result", "{}")); path = result.get("files", {}).get("manifest" if extension == "json" else extension)
    if path and path.startswith("s3://"):
        bucket, object_key = object_store.split_uri(path)
        try:
            response = await asyncio.to_thread(object_store.client().get_object, bucket, object_key)
        except S3Error as exc:
            raise HTTPException(404 if exc.code in {"NoSuchKey", "NoSuchBucket"} else 503, "Stored file unavailable") from exc
        def chunks():
            try:
                yield from response.stream(1024 * 1024)
            finally:
                response.close()
                response.release_conn()
        return StreamingResponse(chunks(), media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{Path(object_key).name}"'})
    if not path or not Path(path).exists(): raise HTTPException(404, f"{extension} is not available")
    return FileResponse(path, filename=Path(path).name)

@app.post("/v1/presentations/{job_id}/regenerate", status_code=202)
async def regenerate(job_id: str, body: RegenerateRequest):
    d = await redis.hgetall(key(job_id))
    if not d or not d.get("request"): raise HTTPException(404, "Original request not found")
    req = json.loads(d["request"])
    req["request_id"] = str(uuid.uuid4())
    if body.prompt:
        req["prompt"] = body.prompt
    if body.slide_id:
        req["_regenerate"] = {
            "base_job_id": job_id,
            "slide_id": body.slide_id,
            "instruction": body.instruction or "",
        }
    elif body.instruction:
        req["prompt"] = (req.get("prompt") or "") + "\nRegeneration instruction: " + body.instruction
    new_id = str(uuid.uuid4())
    await redis.hset(key(new_id), mapping={"job_id": new_id, "user_id": req.get("user_id", "local-user"), "status": "queued", "stage": "queued", "progress": "0", "message": "Regeneration accepted", "request": json.dumps(req, ensure_ascii=False)})
    await redis.expire(key(new_id), settings.job_ttl_hours * 3600)
    try: await start_workflow(new_id, req)
    except Exception as exc: await redis.hset(key(new_id), mapping={"status": "failed", "stage": "submission", "message": str(exc)}); raise HTTPException(503, str(exc)) from exc
    return {"job_id": new_id, "status": "queued", "status_url": f"/v1/presentations/{new_id}", "events_url": f"/v1/presentations/{new_id}/events", "note": "Only the requested slide is rebuilt when slide_id is supplied; otherwise the full deck is regenerated."}
