# MinIO and Temporal payload fix

## Diagnosis
The workflow sends the source pack to each parallel slide activity. It also sends
all slides into review, rendering and visual QA. A workflow task scheduling many
activities can exceed Temporal's message/transaction limit even when each
argument is below its individual payload limit. The reported termination is
consistent with this path; no failed workflow history was supplied to measure
its exact offending message.

Temporal documents default limits of 2 MiB per payload and 4 MiB per gRPC
message/transaction. Raising an application variable does not raise these server
limits. This implementation avoids transporting large data through Temporal.

Reference: https://docs.temporal.io/ai/cookbook/claim-check-pattern-python

## Start
1. Keep your existing LLM and Redis settings in `.env`. Set a new strong
   `MINIO_SECRET_KEY` before the first startup (minimum 8 characters).
2. Run from this folder:

   docker compose up -d --build

3. Open frontend http://localhost:5173, API docs http://localhost:8000/docs,
   Temporal http://localhost:8233, MinIO console http://localhost:9001.
4. Log into MinIO with `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` from `.env`.
   The supplied development values are `pptadmin` / `change-this-minio-password`.
5. Submit a new request ID. Previously terminated workflows remain terminated;
   they cannot be repaired by restarting the worker.

## Environment configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| TEMPORAL_PAYLOAD_INLINE_BYTES | 16384 | Serialized protobuf bytes allowed inline; larger payloads are stored in MinIO |
| MINIO_ENDPOINT | localhost:9000 | API endpoint without scheme; Compose overrides it to minio:9000 |
| MINIO_ACCESS_KEY | pptadmin | MinIO username/access key |
| MINIO_SECRET_KEY | change-this-minio-password | MinIO password/secret key |
| MINIO_SECURE | false | TLS for MinIO API |
| MINIO_PAYLOAD_BUCKET | ppt-temporal-payloads | Private serialized Temporal payloads |
| MINIO_OUTPUT_BUCKET | ppt-generated | PPTX, PDF, thumbnails, manifest and source pack |

Use `TEMPORAL_PAYLOAD_INLINE_BYTES=8192` for 8 KiB or `0` to offload every
payload. Values above 16384 are rejected intentionally: slide-builder command
batches are capped at 20 so repeated inline inputs cannot grow unchecked.
This threshold is not a maximum file size, model context window, input token
limit or Temporal gRPC setting. Restart API and worker after editing it:

    docker compose up -d --build api worker

Both services MUST use the same codec and MinIO credentials. The codec supports
legacy inline payloads as well as new references. New fan-out batching uses a
Temporal patch marker so old histories keep their scheduling behavior.
There is no public codec server: Temporal UI shows object references for
offloaded values rather than their decoded content.

## Storage behavior
- Rendering/LibreOffice/QA still need local working files. After QA and cache
  extraction, `complete_job` uploads final outputs before marking the job complete.
- The existing download endpoints stream MinIO objects; frontend changes are
  unnecessary. Status results contain `s3://...` references, not public URLs.
- Regenerating one slide reads its manifest and source pack from MinIO. Existing
  local completed jobs are also supported while their local files remain.
- Uploads use content-addressed keys; retries cannot corrupt prior versions.
  Each payload is checksum-verified when read. MinIO failures propagate and
  prevent false completion; there is no silent local-only fallback.
- Files already generated before this update are not bulk migrated. New and
  regenerated outputs are uploaded automatically.
- Local working files remain available as before; automatic deletion is not
  introduced. The Redis job TTL still controls availability through job URLs,
  even though MinIO objects survive job metadata expiration.
- `minio_data` is a persistent Docker volume. `docker compose down` preserves it;
  `docker compose down -v` deletes it. Back up this volume for durable storage.
- Do not expire payload objects while a workflow may execute, retry or replay.
  A missing payload prevents replay. No automatic object expiry is configured.
- This Compose setup retains the original Temporal development server. It is
  not a production Temporal deployment and this change does not make its
  workflow history persistent across container replacement.

## Validation
Run `python -m pip install -r requirements.txt` then `python -m pytest -q`.
New tests cover transparent codec round trips, checksum rejection, bounded
thresholds and retry-safe publishing. Tests mock MinIO; for an integration check,
create a 40-slide job (set SLIDES_MAX and MAX_OUTPUT_SLIDES >=40), confirm both
buckets contain objects, download the PPT, and regenerate one slide. Stop MinIO
briefly to verify storage failures do not mark jobs completed. A live Docker,
Temporal, MinIO and model generation test must be run on your machine.

## Changed code
- app/temporal/payload_codec.py: transparent claim-check codec for all boundaries
- app/services/object_store.py: MinIO I/O, private output publishing
- app/main.py, app/worker.py: shared data converter; streamed downloads
- app/temporal/activities.py: final uploads and MinIO regeneration reads
- app/temporal/workflows.py: bounded, replay-aware slide activity scheduling
- app/config.py, .env, .env.example: validated storage/threshold settings
- docker-compose.yml: MinIO server, volume and service configuration
- requirements.txt, tests/test_minio_payloads.py
