import asyncio
import json
import pytest
from app.services import pipeline
from app.schemas import PresentationRequest


def test_topic_mode_is_marked_as_ai_draft(monkeypatch):
    async def chat(*args,**kwargs):
        return json.dumps({'topics':[{'title':t,'summary':'Useful general background about '+t} for t in ['Context','Applications','Engineering','Evaluation']]})
    monkeypatch.setattr(pipeline,'chat',chat)
    pack=asyncio.run(pipeline.source_adapter({'_content_mode':'topic','_query':'AI in India'}))
    assert pack['content_mode']=='topic' and len(pack['topics'])==4
    assert 'not live research' in pack['warnings'][0]
    assert all(t['source_quote']=='' for t in pack['topics'])


def test_topic_drafting_failure_is_explicit(monkeypatch):
    async def chat(*args,**kwargs):return '{"topics":[]}'
    monkeypatch.setattr(pipeline,'chat',chat)
    with pytest.raises(ValueError,match='too few topics'):
        asyncio.run(pipeline.source_adapter({'_content_mode':'topic','_query':'Topic'}))


def test_original_source_request_still_valid():
    request=PresentationRequest(request_id='source-1',text={'type':'plain','content':'A trusted source.'})
    assert request.options.content_mode=='source'


def test_nonfinite_numbers_rejected_in_chart():
    errors=pipeline.validate({'title':'Revenue','chart':{'labels':['A','B'],'values':[float('inf'),1]}},'1')
    assert errors
