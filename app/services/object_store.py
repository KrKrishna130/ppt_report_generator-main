"""Private MinIO storage. Network operations must run outside workflow code."""
import hashlib
import io
import json
import mimetypes
from functools import lru_cache
from pathlib import Path
from minio import Minio
from minio.error import S3Error
from app.config import settings

@lru_cache(maxsize=1)
def client():
    return Minio(settings.minio_endpoint, access_key=settings.minio_access_key,
                 secret_key=settings.minio_secret_key, secure=settings.minio_secure)

def ensure_bucket(bucket):
    if not client().bucket_exists(bucket):
        try:
            client().make_bucket(bucket)
        except S3Error as exc:
            if exc.code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise

def put_bytes(bucket, key, data, content_type="application/octet-stream"):
    ensure_bucket(bucket)
    client().put_object(bucket, key, io.BytesIO(data), len(data), content_type=content_type)
    return f"s3://{bucket}/{key}"

def split_uri(uri):
    bucket, key = uri.removeprefix("s3://").split("/", 1)
    if not uri.startswith("s3://") or bucket not in {settings.minio_payload_bucket, settings.minio_output_bucket}:
        raise ValueError("Untrusted object reference")
    return bucket, key

def get_bytes(uri):
    bucket, key = split_uri(uri)
    response = client().get_object(bucket, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()

def read_json(path):
    return json.loads(get_bytes(path) if path.startswith("s3://") else Path(path).read_bytes())

def upload_file(job_id, path):
    path = Path(path)
    # Content hash keeps retries immutable and distinguishes QA revisions.
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    key = f"presentations/{job_id}/{digest}/{path.name}"
    ensure_bucket(settings.minio_output_bucket)
    client().fput_object(settings.minio_output_bucket, key, str(path),
                        content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    return f"s3://{settings.minio_output_bucket}/{key}"

def publish_outputs(job_id, result):
    """Publish only after QA. Upload source pack before rewriting its manifest."""
    files = result["files"]
    manifest = read_json(files["manifest"])
    manifest["pack_path"] = upload_file(job_id, manifest["pack_path"])
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
    published = {}
    for kind, path in files.items():
        if kind == "manifest":
            digest = hashlib.sha256(manifest_bytes).hexdigest()
            published[kind] = put_bytes(settings.minio_output_bucket,
                f"presentations/{job_id}/{digest}/{Path(path).name}", manifest_bytes, "application/json")
        elif kind == "thumbnails":
            published[kind] = json.dumps([upload_file(job_id, item) for item in json.loads(path)])
        else:
            published[kind] = upload_file(job_id, path)
    return published
