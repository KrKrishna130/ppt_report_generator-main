import asyncio
import json
from pathlib import Path
import pytest
from temporalio.api.common.v1 import Payload
from pydantic import ValidationError
from app.config import Settings
from app.temporal.payload_codec import MinioPayloadCodec, ENCODING
from app.services import object_store


def test_codec_roundtrip_and_checksum(monkeypatch):
    from app.temporal import payload_codec as module
    objects = {}
    def put(bucket, key, raw):
        uri = f's3://{bucket}/{key}'
        objects[uri] = raw
        return uri
    monkeypatch.setattr(object_store, 'put_bytes', put)
    monkeypatch.setattr(object_store, 'get_bytes', objects.__getitem__)
    monkeypatch.setattr(module.settings, 'temporal_payload_inline_bytes', 100)
    async def run():
        codec = MinioPayloadCodec()
        small = Payload(metadata={'encoding': b'json/plain'}, data=b'1')
        big = Payload(metadata={'encoding': b'json/plain'}, data=b'x' * 10000)
        encoded = await codec.encode([small, big])
        assert encoded[0] == small
        assert encoded[1].metadata['encoding'] == ENCODING
        assert (await codec.decode(encoded)) == [small, big]
        await codec.encode([big])
        assert len(objects) == 1  # content-addressed retry
        objects[json.loads(encoded[1].data)['uri']] = b'corrupt'
        with pytest.raises(ValueError, match='checksum'):
            await codec.decode(encoded)
    asyncio.run(run())


def test_threshold_guard():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, temporal_payload_inline_bytes=2000000)


def test_publish_retry_keeps_local_manifest(tmp_path, monkeypatch):
    pack = tmp_path / 'test.pack.json'; pack.write_text('{}')
    manifest = tmp_path / 'test.json'
    original = json.dumps({'pack_path': str(pack), 'slides': []})
    manifest.write_text(original)
    ppt = tmp_path / 'test.pptx'; ppt.write_bytes(b'ppt')
    monkeypatch.setattr(object_store, 'upload_file', lambda job, path: 's3://ppt-generated/' + Path(path).name)
    uploaded = []
    def put(bucket, key, raw, content_type):
        uploaded.append(json.loads(raw))
        return f's3://{bucket}/{key}'
    monkeypatch.setattr(object_store, 'put_bytes', put)
    result = {'files': {'manifest': str(manifest), 'pptx': str(ppt)}}
    for _ in range(2):
        assert object_store.publish_outputs('job', result)['pptx'].startswith('s3://')
    assert manifest.read_text() == original
    assert uploaded[0]['pack_path'].startswith('s3://')
