import asyncio
import json
import pytest
from app.schemas import PresentationRequest
from app.services.pipeline import resolve, parse_prompt
from app.services.content_cache import content_key

@pytest.mark.parametrize('prompt,count', [('Create 15 slides',15),('slide create 15 slide',15),('color is Red and slide 17',17)])
def test_prompt_count_and_override(prompt,count):
    r,t=resolve({}, {'slide_count':6}, {}, prompt)
    assert r['slide_count']['value']==count
    r,t=resolve({'slide_count':9}, {}, {}, prompt)
    assert r['slide_count']['value']==9

@pytest.mark.parametrize('prompt,color', [('Terrorism in India','crimson'),('bank authority','navy'),('constitution','burgundy'),('cyber security','electric'),('environment','forest'),('water','teal'),('education','navy'),('Terrorism in India, color is Red and slide 17','red')])
def test_domain_and_prompt_colors(prompt,color):
    r,t=resolve({}, {}, {}, prompt)
    assert r['theme_color']['value']==color
    assert t['design_theme']=='custom'
    if color=='red': assert t['primary']=='#DC2626'


def test_nullable_options_and_notes():
    r=PresentationRequest(request_id='a',prompt='Create 15 slides without speaker notes',options={'content_mode':None,'design_theme':None,'speaker_notes':None})
    assert r.options.content_mode=='topic' and r.options.speaker_notes is False
    r=PresentationRequest(request_id='a',text={'content':'Source'},options={'content_mode':None})
    assert r.options.content_mode=='source'


def test_cache_identity():
    a=PresentationRequest(request_id='a',user_id='x',prompt='Create 15 slides').model_dump()
    b=PresentationRequest(request_id='b',user_id='y',prompt='Create 15 slides').model_dump()
    assert content_key(a)==content_key(b)
    b['options']['slide_count']=17
    assert content_key(a)!=content_key(b)


def test_llm_cannot_override_explicit_count(monkeypatch):
    from app.services import pipeline
    async def chat(*args,**kwargs):return '{"slide_count":8,"theme_color":"blue"}'
    monkeypatch.setattr(pipeline,'chat',chat)
    result=asyncio.run(parse_prompt('color is Red and slide 17'))
    assert result['slide_count']==17 and result['theme_color']=='red'


def test_cache_hit_skips_generation_and_renders_new_job(monkeypatch):
    from app.temporal import activities
    calls=[]
    cached={'resolved_settings':{},'theme':{},'outline':[],'slides':[{'title':'Cached'}],'pack':{},'warnings':[]}
    class Redis:
        async def get(self,key):return json.dumps(cached)
    async def render(*args):
        calls.append(args)
        return {'files':{'pptx':'new-file'}}
    monkeypatch.setattr(activities,'redis',Redis())
    monkeypatch.setattr(activities,'render_outputs',render)
    result=asyncio.run(activities.reuse_cached_content('new-job',{'prompt':'Topic'}))
    assert result['cache_hit'] and calls[0][0]=='new-job'
    assert calls[0][5]==cached['slides']


def test_actual_seventeen_slide_export(tmp_path):
    from app.services.pipeline import fallback_outline
    from app.services.render import render_pptx
    from pptx import Presentation
    request=PresentationRequest(request_id='17',prompt='History of Terrorism in India, color is Red and slide 17')
    pack={'topics':[{'title':'Historical overview','summary':'Background and context.'}]}
    resolved,theme=resolve(request.options.model_dump(),{},pack,request.prompt)
    slides=[dict(s,title=s['key_message'],subtitle='Background and context.',items=[{'title':'Context','body':'Historical overview.'}]) for s in fallback_outline(pack, resolved['slide_count']['value'])]
    path=tmp_path/'seventeen.pptx'
    render_pptx(slides,theme,resolved,path,request.options.model_dump())
    assert len(Presentation(path).slides)==17
    assert theme['primary']=='#DC2626'


def test_concurrent_request_waits_for_cached_content(monkeypatch):
    from app.temporal import activities
    cached={'resolved_settings':{},'theme':{},'outline':[],'slides':[],'pack':{}}
    class Redis:
        ready=False
        async def get(self,key):
            if key.endswith(':lock'):return 'first-job'
            return json.dumps(cached) if self.ready else None
        async def set(self,*args,**kwargs):return False
    redis=Redis()
    waits=[]
    async def sleep(seconds):waits.append(seconds);redis.ready=True
    async def render(*args):return {'files':{}}
    monkeypatch.setattr(activities,'redis',redis)
    monkeypatch.setattr(activities.asyncio,'sleep',sleep)
    monkeypatch.setattr(activities,'render_outputs',render)
    result=asyncio.run(activities.reuse_cached_content('second-job',{'prompt':'Topic'}))
    assert waits==[2] and result['cache_hit'] is True
