"""Claim check for every API/worker Temporal boundary, including workflow start."""
import asyncio
import hashlib
import json
from dataclasses import replace
from temporalio.api.common.v1 import Payload
from temporalio.converter import DataConverter, PayloadCodec
from app.config import settings
from app.services import object_store

ENCODING = b"binary/minio-claim-check-v1"

class MinioPayloadCodec(PayloadCodec):
    async def encode(self, payloads):
        result = []
        for payload in payloads:
            raw = payload.SerializeToString(deterministic=True)
            if len(raw) <= settings.temporal_payload_inline_bytes:
                result.append(payload)
                continue
            digest = hashlib.sha256(raw).hexdigest()
            uri = await asyncio.to_thread(object_store.put_bytes,
                settings.minio_payload_bucket, f"sha256/{digest}.payload", raw)
            result.append(Payload(metadata={"encoding": ENCODING},
                data=json.dumps({"uri": uri, "sha256": digest}).encode()))
        return result

    async def decode(self, payloads):
        result = []
        for payload in payloads:
            if payload.metadata.get("encoding") != ENCODING:
                result.append(payload)
                continue
            ref = json.loads(payload.data)
            raw = await asyncio.to_thread(object_store.get_bytes, ref["uri"])
            if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
                raise ValueError("Temporal payload checksum mismatch")
            result.append(Payload.FromString(raw))
        return result

def data_converter():
    return replace(DataConverter.default, payload_codec=MinioPayloadCodec())
