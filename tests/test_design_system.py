import asyncio
import hashlib
from pathlib import Path
import pytest
from pptx import Presentation
from app.schemas import PresentationRequest, Options
from app.services.design import THEMES, apply_theme, choose_layout
from app.services.pipeline import resolve, validate, plan, build, source_adapter
from app.services.render import render_pptx, render_pdf, render_thumbnails


def test_query_only_requires_topic_mode():
    assert PresentationRequest(request_id='a',prompt='AI in India').options.content_mode == 'topic'
    r=PresentationRequest(request_id='a',prompt='AI in India',options={'content_mode':'topic'})
    assert r.text.content=='AI in India'


@pytest.mark.parametrize('query,design',[
 ('Artificial Intelligence Development: Evolution, Current State, and Future Trajectory in India','dark_lime'),
 ('Competitive Sales Battlecard Playbook','editorial_purple'),
 ('Unified Operations Platform: Mid-Market Sales Pitch','corporate_blue'),
 ('what is ai developements in india.','india_yellow')])
def test_theme_matches_reference_query(query,design):
    _,t=resolve({}, {}, {'topics':[{'title':query}]}, query)
    assert t['design_theme']==design and t['design_version']==2


def test_source_numbers_in_new_structures_are_checked():
    assert any('Unsupported number' in e for e in validate({'title':'Results','items':[{'title':'ROI','body':'42% improvement'}]},'No metrics supplied'))
    assert validate({'title':'Results','kpis':[{'value':'42%','label':'Improvement'}]},'42% improvement')==[]


def test_colors_are_validated():
    with pytest.raises(ValueError):Options(brand_colors=['not-a-color'])


def sample(layout):
    return {'id':layout,'title':'Connected operations platform','layout_variant':layout,
            'subtitle':'Teams share trusted information and coordinate their work.',
            'items':[{'title':t,'body':'Connect source systems and coordinate work across departments.'} for t in ['Shared data','Workflow automation','Governance','Team enablement']],
            'timeline':[{'date':f'Phase {i+1}','label':t,'body':'Review scope and confirm ownership.'} for i,t in enumerate(['Discovery','Setup','Pilot','Rollout'])],
            'kpis':[{'value':'3.2x','label':'Illustrative ROI'},{'value':'30%','label':'Illustrative cost reduction'},{'value':'4 months','label':'Illustrative payback'}],
            'table':{'headers':['Capability','Fragmented tools','Unified platform'],'rows':[['Data','Siloed','Shared'],['Workflows','Manual','Coordinated'],['Access','Separate','Centralized']]},
            'chart':{'type':'bar','title':'Illustrative data','labels':['A','B','C'],'values':[10,20,30]}}


@pytest.mark.parametrize('name',list(THEMES))
def test_all_compositions_are_editable_and_on_canvas(tmp_path,name):
    theme=apply_theme({}, {'design_theme':name}, '')
    layouts=['hero','numbered','pillars','timeline','steps','pyramid','hub','cycle','kpi_split','comparison','two_column','chart']
    out=tmp_path/(name+'.pptx');render_pptx([sample(l) for l in layouts],theme,{},out,{'speaker_notes':True})
    p=Presentation(out)
    assert len(p.slides)==len(layouts)
    assert any(sh.has_table for s in p.slides for sh in s.shapes)
    assert any(sh.has_chart for s in p.slides for sh in s.shapes)
    for s in p.slides:
        assert any(sh.has_text_frame for sh in s.shapes)
        for sh in s.shapes:
            assert sh.left>=0 and sh.top>=0
            assert sh.left+sh.width<=p.slide_width+100 and sh.top+sh.height<=p.slide_height+100


def test_offline_pipeline_uses_new_layouts_and_preserves_evidence(monkeypatch):
    from app.services import pipeline
    async def mock_chat(model,system,prompt,**kwargs):
        if 'Plan' in system:
            return '{"slides":[{"id":"s1","key_message":"Overview","topic_refs":[0]},{"id":"s2","key_message":"Four core pillars","topic_refs":[0]},{"id":"s3","key_message":"Feedback loop","topic_refs":[0]},{"id":"s4","key_message":"Next steps","topic_refs":[0]}]}'
        return '{"title":"Shared operations","items":[{"title":"Governance","body":"Teams share ownership."}],"bullets":[],"source_quotes":[]}'
    monkeypatch.setattr(pipeline,'chat',mock_chat)
    pack={'topics':[{'title':'Operations','summary':'Teams share ownership.'}],'source_text':'Teams share ownership.'}
    resolved,theme=resolve({'slide_count':4}, {},pack,'Operations')
    outline=asyncio.run(plan(pack,resolved,'Operations'))
    assert [s['layout_variant'] for s in outline]==['hero','pillars','cycle','numbered']
    slide=asyncio.run(build(outline[1],pack,'Operations',theme))
    assert slide['items'][0]['title']=='Governance' and slide['layout_variant']=='pillars'
    assert validate(slide,pack['source_text'])==[]
