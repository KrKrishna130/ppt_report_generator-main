import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';



import { createRoot } from 'react-dom/client';



import { Activity, AlertCircle, ArrowDownToLine, ArrowRight, ArrowUpRight, Bell, Check, CheckCircle2, ChevronDown, ChevronRight, CircleHelp, Clock3, Code2, Copy, Download, ExternalLink, FileJson, FileText, Globe, HardDrive, History, LayoutDashboard, LoaderCircle, Menu, MessageSquareText, Play, Plus, RefreshCw, Settings2, ShieldCheck, Sparkles, Terminal, Trash2, Workflow, X, Zap } from 'lucide-react';



// Fonts are bundled (no Google Fonts request), so the dashboard looks the same offline.

import '@fontsource/dm-mono/400.css';

import '@fontsource/dm-mono/500.css';

import '@fontsource/dm-sans/400.css';

import '@fontsource/dm-sans/500.css';

import '@fontsource/dm-sans/600.css';

import '@fontsource/dm-sans/700.css';

import '@fontsource/manrope/400.css';

import '@fontsource/manrope/500.css';

import '@fontsource/manrope/600.css';

import '@fontsource/manrope/700.css';

import '@fontsource/manrope/800.css';

import './styles.css';
import AIStudio from './AIStudio.jsx';





// it is Default will works

// The API runs on the same host as the dashboard, so a browser on another machine reaches it too.

const DEFAULT_API=`http://${window.location.hostname||'localhost'}:8000`;



const SAMPLE='Renewable energy comes from naturally replenished sources. Solar energy converts sunlight into electricity. Wind energy uses turbines to generate electricity. Both can reduce dependence on fossil fuels, although performance depends on location, weather, infrastructure, and storage. Key considerations include installation costs, maintenance, grid integration, and environmental impacts.';



const DEFAULT_PROMPT='Create a concise, professional 4-slide presentation explaining the benefits of renewable energy. Include an introduction, a comparison of solar and wind energy, key benefits, and a conclusion. Use a green theme and concise speaker notes.';



// This Logiic written for if CORSE error or api Url mismatch happen then its works.

const normalizeApiBase=(value)=>{

  try {

    const parsed = new URL(String(value || DEFAULT_API).trim());

    if (!['http:', 'https:'].includes(parsed.protocol)) return DEFAULT_API;

    return parsed.origin;

  } catch {

    return DEFAULT_API;

  }

};



const url=(base,path)=>`${normalizeApiBase(base)}/${String(path).replace(/^\/+/, '')}`;



const timeNow=()=>new Intl.DateTimeFormat('en-IN',{hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date());



const json=v=>typeof v==='string'?v:JSON.stringify(v,null,2);



function App(){



 const [base,setBase]=useState(()=>normalizeApiBase(localStorage.getItem('deckflow_api')||DEFAULT_API)),[page,setPage]=useState('overview'),[navOpen,setNavOpen]=useState(false);



 const [health,setHealth]=useState({api:'checking',temporal:'checking',redis:'unknown',address:''}),[checking,setChecking]=useState(false);



 const [requestId,setRequestId]=useState(`deckflow-${Date.now().toString().slice(-8)}`),[userId,setUserId]=useState('demo-user-01'),[prompt,setPrompt]=useState(DEFAULT_PROMPT),[source,setSource]=useState(SAMPLE),[sourceType,setSourceType]=useState('plain'),[slides,setSlides]=useState(''),[theme,setTheme]=useState(''),[language,setLanguage]=useState('English'),[seed,setSeed]=useState('12345'),[notes,setNotes]=useState(true),[pptx,setPptx]=useState(true),[pdf,setPdf]=useState(true),[callback,setCallback]=useState('');



 const [designTheme,setDesignTheme]=useState('auto'),[contentMode,setContentMode]=useState('source');



 const [submitting,setSubmitting]=useState(false),[job,setJob]=useState(null),[jobResponse,setJobResponse]=useState(null),[error,setError]=useState(''),[events,setEvents]=useState([]),[logs,setLogs]=useState([]),[toast,setToast]=useState('');



 const [originalId,setOriginalId]=useState(''),[slideId,setSlideId]=useState('s2'),[instruction,setInstruction]=useState('Shorten the bullet points, improve readability, and retain all source-supported facts.'),[regenBusy,setRegenBusy]=useState(false);



 const esRef=useRef(null); const logCounter=useRef(0);



 const log=useCallback((method,path,status,detail)=>setLogs(old=>[{id:++logCounter.current,time:timeNow(),method,path,status,detail},...old].slice(0,50)),[]);



 const request=useCallback(async(path,opts={})=>{const method=opts.method||'GET';try{const r=await fetch(url(base,path),{...opts,headers:{...(opts.body?{'Content-Type':'application/json'}:{}),...opts.headers}});const t=await r.text();let data;try{data=JSON.parse(t)}catch{data=t}log(method,path,r.status,r.ok?'Success':(data?.detail||data?.message||String(data)));if(!r.ok)throw new Error(data?.detail||data?.message||String(data)||`HTTP ${r.status}`);return data}catch(e){if(!logs.some(x=>x.path===path&&x.status==='ERR'))log(method,path,'ERR',e.message);throw e}},[base,log]);



 const checkHealth=useCallback(async()=>{setChecking(true);try{const d=await request('/health');setHealth(h=>({...h,api:'ok',redis:d?.redis||'unknown'}))}catch{setHealth(h=>({...h,api:'error',redis:'unknown'}))}try{const d=await request('/health/temporal');setHealth(h=>({...h,temporal:d?.status==='ok'?'ok':'warning',address:d?.address||''}))}catch{setHealth(h=>({...h,temporal:'error',address:''}))}setChecking(false)},[request]);



 useEffect(()=>{checkHealth()},[checkHealth]);useEffect(()=>localStorage.setItem('deckflow_api',normalizeApiBase(base)),[base]);useEffect(()=>{if(!toast)return;const t=setTimeout(()=>setToast(''),2600);return()=>clearTimeout(t)},[toast]);useEffect(()=>()=>esRef.current?.close(),[]);



 const body=useMemo(()=>({request_id:requestId.trim(),user_id:userId.trim(),prompt,text:contentMode==='topic'?undefined:(sourceType==='chat'?{type:'chat',messages:[{id:'m1',role:'user',content:source}]}:{type:'plain',content:source}),options:{slide_count:slides===''?null:Number(slides),language,theme:theme||undefined,design_theme:designTheme,content_mode:contentMode,seed:seed.trim()===''?null:Number(seed),speaker_notes:notes,output:[pptx&&'pptx',pdf&&'pdf'].filter(Boolean)},callback_url:callback.trim()||null}),[requestId,userId,prompt,sourceType,source,slides,language,theme,designTheme,contentMode,seed,notes,pptx,pdf,callback]);



 const status=String(job?.status||'idle').toLowerCase(),done=status==='completed',failed=['failed','error','cancelled','canceled'].includes(status),running=['queued','running','processing','started','in_progress'].includes(status),progress=Math.max(0,Math.min(100,Number(job?.progress??(done?100:0))));



 const refreshJob=useCallback(async(id,announce=false)=>{if(!id)return;try{const d=await request(`/v1/presentations/${encodeURIComponent(id)}`);setJob(old=>({...old,...d,job_id:d.job_id||id}));setJobResponse(d);if(announce)setToast('Job status refreshed');return d}catch(e){setError(e.message)}},[request]);



 useEffect(()=>{if(!job?.job_id||!running)return;const t=setInterval(()=>refreshJob(job.job_id),5000);return()=>clearInterval(t)},[job?.job_id,running,refreshJob]);



 async function submit(e){e?.preventDefault();setError('');if(!body.request_id||!body.user_id||!prompt.trim()||(contentMode==='source'&&!source.trim()))return setError('Request ID, user ID, prompt, and source content in source mode are required.');if(!body.options.output.length)return setError('Choose at least one output format.');setSubmitting(true);setEvents([]);try{const d=await request('/v1/presentations',{method:'POST',body:JSON.stringify(body)});setJobResponse(d);setJob({...d,job_id:d.job_id||d.id,status:d.status||'queued',progress:d.progress||0});setPage('monitor');setToast('Presentation job submitted');if(d.job_id||d.id)await refreshJob(d.job_id||d.id)}catch(e){setError(e.message)}finally{setSubmitting(false)}}



 function connectEvents(){const id=job?.job_id||job?.id;if(!id)return setError('Submit a presentation or load an existing job ID first.');esRef.current?.close();setEvents(old=>[{time:timeNow(),type:'client',data:'Connecting to server-sent events…'},...old]);try{const es=new EventSource(url(base,`/v1/presentations/${encodeURIComponent(id)}/events`));esRef.current=es;es.onopen=()=>setEvents(old=>[{time:timeNow(),type:'connected',data:'Event stream connected'},...old]);es.onmessage=e=>setEvents(old=>[{time:timeNow(),type:'message',data:e.data},...old].slice(0,100));['connected','progress','stage','terminal','error'].forEach(type=>es.addEventListener(type,e=>{setEvents(old=>[{time:timeNow(),type,data:e.data||''},...old].slice(0,100));if(type==='terminal'){try{const d=JSON.parse(e.data);if(d.status)setJob(old=>({...old,status:d.status,message:d.message||old?.message,progress:d.status==='completed'?100:old?.progress}))}catch{}es.close();refreshJob(id)}}));es.onerror=()=>setEvents(old=>[{time:timeNow(),type:'notice',data:'Event stream disconnected; refresh status or reconnect.'},...old].slice(0,100))}catch(e){setError(e.message)}}



 async function download(ext){const id=job?.job_id||job?.id;if(!id)return setError('No job ID available for download.');const path=`/v1/presentations/${encodeURIComponent(id)}/download.${ext}`;try{const r=await fetch(url(base,path));if(!r.ok)throw new Error((await r.text())||`Download failed (${r.status})`);const blob=await r.blob(),disp=r.headers.get('content-disposition')||'',name=disp.match(/filename="?([^\\\\"]+)"?/i)?.[1]||`presentation-${id}.${ext}`,href=URL.createObjectURL(blob),a=document.createElement('a');a.href=href;a.download=name;document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(href);log('GET',path,r.status,`Downloaded ${name}`);setToast(`${ext.toUpperCase()} download started`)}catch(e){setError(e.message)}}



 async function regenerate(e){e?.preventDefault();setError('');const id=originalId.trim()||job?.job_id||job?.id;if(!id)return setError('Enter the original presentation job ID.');if(!instruction.trim())return setError('Enter revision instructions.');setRegenBusy(true);try{const b={instruction};if(slideId.trim())b.slide_id=slideId.trim();const d=await request(`/v1/presentations/${encodeURIComponent(id)}/regenerate`,{method:'POST',body:JSON.stringify(b)});setJob({...d,job_id:d.job_id||d.id,status:d.status||'queued',progress:0});setJobResponse(d);setPage('monitor');setToast('Regeneration job submitted')}catch(e){setError(e.message)}finally{setRegenBusy(false)}}



 async function copy(v){try{await navigator.clipboard.writeText(v);setToast('Copied to clipboard')}catch{setToast('Clipboard access unavailable')}}



 const go=p=>{setPage(p);setNavOpen(false);setError('')};



 const routes=[['GET','/health','Check API and Redis'],['GET','/health/temporal','Check Temporal connection'],['POST','/v1/presentations','Create presentation job'],['GET','/v1/presentations/{job_id}','Read job status and result'],['GET','/v1/presentations/{job_id}/events','Listen to SSE events'],['GET','/v1/presentations/{job_id}/download.{extension}','Download PPTX or PDF'],['POST','/v1/presentations/{job_id}/regenerate','Regenerate a slide or deck']];



 const nav=[{title:'WORKSPACE',items:[['overview','Overview',LayoutDashboard],['create','Create presentation',Sparkles],['studio','Presentation.AI',Sparkles],['monitor','Job monitor',Activity],['regenerate','Regenerate slide',RefreshCw]]},{title:'DEVELOPER TOOLS',items:[['logs','Request history',History],['settings','API settings',Settings2]]}];



 return <div className="shell"><aside className={`sidebar ${navOpen?'open':''}`}><div className="brand"><div className="brandmark">D</div><div><strong>PPT GENERATION SERVICE<span>·</span></strong><small>DASHBOARD</small></div><button className="icon close-nav" onClick={()=>setNavOpen(false)}><X size={17}/></button></div><div className="workspace"><div className="workspace-icon">P</div><div><strong>PPT Generator</strong><small>Local workspace</small></div><ChevronDown size={14}/></div><nav>{nav.map(g=><div className="navgroup" key={g.title}><div className="navtitle">{g.title}</div>{g.items.map(([id,label,Icon])=><button key={id} className={`navitem ${page===id?'active':''}`} onClick={()=>go(id)}><Icon size={17}/><span>{label}</span>{id==='create'&&<em>API</em>}</button>)}</div>)}</nav><div className="sidebarbottom"><div className="local-card"><ShieldCheck size={18}/><div><strong>Local-first workflow</strong><p>Your requests go to your configured API.</p></div></div><button className="navitem" onClick={()=>go('settings')}><CircleHelp size={17}/><span>Connection help</span></button><div className="profile"><div>D</div><span><strong>Developer</strong><small>API tester</small></span><span className="profile-more">···</span></div></div></aside>{navOpen&&<div className="scrim" onClick={()=>setNavOpen(false)}/>}



 <main><header className="topbar"><div className="crumb"><button className="icon mobile-menu" onClick={()=>setNavOpen(true)}><Menu size={18}/></button>Workspace <ChevronRight size={14}/><strong>{{overview:'Overview',create:'Create presentation',studio:'Presentation.AI',monitor:'Job monitor',regenerate:'Regenerate slide',logs:'Request history',settings:'API settings'}[page]}</strong></div><div className="topactions"><span className="api-indicator"><i className={`dot ${health.api==='ok'?'green':health.api==='error'?'red':'yellow'}`}/>{health.api==='ok'?'API connected':health.api==='checking'?'API checking':'API offline'}</span><button className="icon" onClick={checkHealth} disabled={checking} title="Refresh health">{checking?<LoaderCircle className="spin" size={17}/>:<Bell size={17}/>}</button><button className="avatar" onClick={()=>go('settings')}>D</button></div></header>



 <div className="content">



 {page==='studio'&&<AIStudio apiBase={base} onJob={d=>{setJob(old=>({...old,...d,job_id:d.job_id||d.id||old?.job_id}));setJobResponse(d)}}/>}

 {page==='overview'&&<section className="enter"><div className="hero"><div><div className="eyebrow"><i/> LOCAL API WORKSPACE</div><h1>Build presentations.<br/><span>Test every step.</span></h1><p>One clear workflow for creating, monitoring, and refining AI-generated decks.</p></div><div className="hero-art"><div className="orb"/><div className="slide-art"><div className="slide-dots"><i/><i/><i/></div><b/><span/><span/><div className="bars"><i/><i/><i/><i/><i/></div></div><div className="float-chip chip1"><Check size={13}/> API workflow</div><div className="float-chip chip2"><Sparkles size={14}/> AI powered</div></div></div>



 <div className="health-grid"><Health title="FastAPI service" status={health.api} subtitle={health.api==='ok'?base:'Check backend and CORS'} icon={Globe} click={()=>window.open(url(base,'docs'),'_blank')}/><Health title="Temporal" status={health.temporal} subtitle={health.address||'Workflow connection'} icon={Workflow}/><Health title="Redis" status={health.redis==='ok'?'ok':health.api==='ok'?'warning':'unknown'} subtitle={health.redis==='ok'?'Status store reachable':'See /health response'} icon={HardDrive}/></div>



 <div className="sectionhead"><div><div className="eyebrow">YOUR WORKFLOW</div><h2>What would you like to do?</h2></div><button className="linkbutton" onClick={()=>go('settings')}>Configure API <ArrowRight size={14}/></button></div><div className="actiongrid"><Action icon={Sparkles} color="violet" step="STEP 01" title="Create a presentation" text="Send a request with your prompt, content, theme, and export options." foot="POST /v1/presentations" click={()=>go('create')}/><Action icon={Activity} color="blue" step="STEP 02" title="Monitor a job" text="Inspect status, progress, workflow events, and generated files." foot="STATUS · SSE · DOWNLOAD" click={()=>go('monitor')}/><Action icon={RefreshCw} color="orange" step="STEP 03" title="Refine a slide" text="Submit revision instructions for one slide or regenerate the deck." foot="POST /regenerate" click={()=>go('regenerate')}/></div>



 <div className="bottomgrid"><div className="panel"><PanelHead title="API route map" sub="Your presentation service at a glance" extra="7 endpoints"/><div className="route-list">{routes.slice(0,5).map(r=><Route key={r[1]} row={r}/>)}</div><button className="linkbutton panel-link" onClick={()=>go('settings')}>View all endpoints <ArrowRight size={14}/></button></div><div className="panel"><PanelHead title="Quick start" sub="Ready to run a test?"/><div className="quicksteps"><div><i className="check"><Check size={12}/></i>Start Docker services</div><div><i className={health.api==='ok'?'check':'pending'}>{health.api==='ok'?<Check size={12}/>:'2'}</i>Verify API health <small>{health.api==='ok'?'Connected':'Check'}</small></div><div><i className={done?'check':'pending'}>{done?<Check size={12}/>:'3'}</i>Generate your first deck</div></div><button className="btn primary full" onClick={()=>go('create')}><Plus size={15}/> Start new test <ArrowRight size={15}/></button></div></div></section>}



 {page==='create'&&<section className="enter"><PageTitle eyebrow="STEP 01 · CREATE" title="Create a presentation" sub="Configure your request and send it to the FastAPI endpoint." right={<button className="btn quiet" onClick={()=>{setPrompt(DEFAULT_PROMPT);setSource(SAMPLE);setTheme('green');setSlides(4);setToast('Sample payload restored')}}><RefreshCw size={14}/> Load sample</button>}/><div className="creategrid"><form className="panel formpanel" onSubmit={submit}><Section n="01" title="Request details" sub="IDs should be unique for each test."/><div className="fields two"><Field label="Request ID" hint="Unique idempotency key"><input value={requestId} onChange={e=>setRequestId(e.target.value)} required/></Field><Field label="User ID"><input value={userId} onChange={e=>setUserId(e.target.value)} required/></Field></div><Field label="Presentation prompt" hint="Be explicit about slide content, charts, and visual style."><textarea rows="5" value={prompt} onChange={e=>setPrompt(e.target.value)} required/></Field><Field label="Content mode"><select value={contentMode} onChange={e=>setContentMode(e.target.value)}><option value="source">Source grounded: use supplied facts</option><option value="topic">Topic: draft from AI general knowledge</option></select>{contentMode==='topic'&&<small>Topic drafts are not live research. Review facts before presenting.</small>}</Field><div className="presets"><span>REFERENCE EXAMPLES</span><div>{[['AI evolution','Artificial Intelligence Development: Evolution, Current State, and Future Trajectory in India','dark_lime',11],['Sales battlecard','Competitive Sales Battlecard Playbook','editorial_purple',11],['Operations pitch','Unified Operations Platform: Mid-Market Sales Pitch','corporate_blue',11],['AI in India','what is ai developements in india.','india_yellow',8]].map(([label,query,design,count])=><button type="button" key={design} onClick={()=>{setPrompt(query);setDesignTheme(design);setTheme('');setContentMode('topic');setSlides(count);setRequestId(`deck-${Date.now()}`)}}>{label}</button>)}</div></div><Section n="02" title="Source content" sub="Provide the source facts used by your pipeline."/><div className="segmented"><button type="button" className={sourceType==='plain'?'selected':''} onClick={()=>setSourceType('plain')}>Plain text</button><button type="button" className={sourceType==='chat'?'selected':''} onClick={()=>setSourceType('chat')}>Chat-style text</button></div><Field label="Content" hint={`${source.length.toLocaleString()} characters`}><textarea rows="5" value={source} onChange={e=>setSource(e.target.value)} required={contentMode==='source'} disabled={contentMode==='topic'}/></Field><Section n="03" title="Output & design" sub="Choose slide count, theme, and export formats."/><div className="fields two"><Field label="Number of slides"><select value={slides} onChange={e=>setSlides(e.target.value)}><option value="">Automatic (from prompt)</option>{Array.from({length:17},(_,i)=>i+4).map(n=><option key={n}>{n}</option>)}</select></Field><Field label="Language"><select value={language} onChange={e=>setLanguage(e.target.value)}>{['English','Hindi','Spanish','French'].map(x=><option key={x}>{x}</option>)}</select></Field></div><Field label="Reference design"><select value={designTheme} onChange={e=>{setDesignTheme(e.target.value);setTheme('')}}>{[['auto','Auto: choose from topic'],['dark_lime','Part 1: Dark lime AI'],['editorial_purple','Part 2: Purple editorial'],['corporate_blue','Part 3: Blue corporate'],['india_yellow','Part 4: Yellow India AI'],['legacy','Original renderer']].map(([v,label])=><option key={v} value={v}>{label}</option>)}</select></Field><Field label="Color override (optional)"><div className="themes">{[['green','#49a77b'],['orange','#ef9656'],['purple','#8b7cf6'],['teal','#228e9b'],['red','#d96772'],['blue','#5e9eea']].map(([name,color])=><button type="button" className={theme===name?'chosen':''} key={name} onClick={()=>setTheme(name)}><i style={{background:color}}/>{name}{theme===name&&<Check size={12}/>}</button>)}</div></Field><div className="fields two"><Field label="Seed" hint="Optional deterministic seed"><input type="number" value={seed} onChange={e=>setSeed(e.target.value)}/></Field><Field label="Callback URL" hint="Leave empty to send null"><input type="url" value={callback} onChange={e=>setCallback(e.target.value)} placeholder="https://example.com/callback"/></Field></div><div className="options"><label><input type="checkbox" checked={notes} onChange={e=>setNotes(e.target.checked)}/> Speaker notes</label><span>EXPORT</span><label><input type="checkbox" checked={pptx} onChange={e=>setPptx(e.target.checked)}/> PPTX</label><label><input type="checkbox" checked={pdf} onChange={e=>setPdf(e.target.checked)}/> PDF</label></div>{error&&<ErrorBox text={error}/>}<div className="submitrow"><span><ShieldCheck size={14}/> Sends to <code>{base}</code></span><button className="btn primary" type="submit" disabled={submitting}>{submitting?<LoaderCircle className="spin" size={15}/>:<Play size={14}/>} {submitting?'Submitting…':'Generate presentation'} <ArrowRight size={14}/></button></div></form><aside className="sidecol"><div className="panel"><PanelHead title="Live request preview" sub="JSON sent to your API" extra={<button className="icon small" onClick={()=>copy(json(body))}><Copy size={14}/></button>}/><pre className="code">{json(body)}</pre></div><div className="tip"><Sparkles size={17}/><div><strong>Pro tip for chart testing</strong><p>Ask for a chart type explicitly. Tell the model to label synthetic data as illustrative and explain axis units.</p><button onClick={()=>{setPrompt('Create a professional 4-slide presentation about monthly sales performance. Include an introduction, a BAR CHART of January to April sales using clearly labeled illustrative sample data, insights, and recommendations. Label both axes, include units, use a professional blue theme, and add concise speaker notes.');setTheme('blue');setToast('Bar chart prompt loaded')}}>Try a bar-chart prompt <ArrowRight size={12}/></button></div></div><div className="panel checklist"><strong>Before you run</strong><p><CheckCircle2 size={14}/> API health check passes</p><p><CheckCircle2 size={14}/> Source content is non-empty</p><p><CheckCircle2 size={14}/> At least one output selected</p><p><AlertCircle size={14}/> Job IDs are unique per test</p></div></aside></div></section>}



 {page==='monitor'&&<section className="enter"><PageTitle eyebrow="STEP 02 · OBSERVE" title="Job monitor" sub="Follow a generation job from queued to completed and inspect its outputs." right={<button className="btn quiet" onClick={()=>refreshJob(job?.job_id||job?.id,true)} disabled={!job}><RefreshCw size={14}/> Refresh status</button>}/>{!job?<div className="panel empty"><div className="emptyicon"><Activity size={24}/></div><h3>No active job yet</h3><p>Create a presentation first, or enter a job ID to inspect an existing job.</p><button className="btn primary" onClick={()=>go('create')}><Plus size={14}/> Create a presentation</button><div className="lookup"><input id="jobid" placeholder="Paste an existing job ID"/><button className="btn secondary" onClick={()=>{const v=document.getElementById('jobid').value.trim();if(v)refreshJob(v)}}>Load job</button></div></div>:<><div className="panel summary"><div className="summarytop"><div className="summaryicon">{done?<CheckCircle2 size={22}/>:failed?<AlertCircle size={22}/>:running?<LoaderCircle className="spin" size={22}/>:<Clock3 size={22}/>}</div><div className="summarytext"><div className="titleline"><h2>{done?'Presentation ready':failed?'Generation failed':running?'Generating your presentation…':'Job submitted'}</h2><Status status={status}/></div><p>{job.message||(done?'Your presentation files are ready.':'Waiting for workflow status…')}</p></div><button className="icon" onClick={()=>copy(job.job_id||job.id||'')}><Copy size={15}/></button></div><div className="jobid"><span>JOB ID</span><code>{job.job_id||job.id||'Not returned by API'}</code><button className="linkbutton" onClick={()=>copy(job.job_id||job.id||'')}>Copy ID</button></div><div className="progresslabel"><span>Overall progress</span><b>{progress}%</b></div><div className="progress"><i style={{width:`${progress}%`}}/></div><div className="stages">{['queued','source_adapter','planner','validate','global_review','render','completed'].map((s,i)=>{const ci=['queued','source_adapter','planner','validate','global_review','render','completed'].indexOf(String(job.stage||status).toLowerCase()),finished=done||i<ci||(i===0&&running);return <div className={`${finished?'finished':''} ${!done&&!failed&&i===ci?'current':''}`} key={s}><i>{finished?<Check size={10}/>:i+1}</i><span>{s.replace('_',' ')}</span></div>})}</div></div><div className="monitorgird"><div className="panel"><PanelHead title="Workflow events" sub="Live server-sent events from your API" extra={<button className="btn secondary smallbtn" onClick={connectEvents}><Activity size={13}/> Connect SSE</button>}/>{events.length===0?<EmptyEvents/>:<div className="eventlist">{events.map((e,i)=><div className="event" key={i}><b>{e.type}</b><code>{e.data}</code><time>{e.time}</time></div>)}</div>}</div><div className="panel"><PanelHead title="Generated files" sub="Available after completion" extra={<FileText size={17}/>}/>{done?<><FileRow ext="PPTX" title="PowerPoint presentation" onClick={()=>download('pptx')}/><FileRow ext="PDF" title="PDF document" onClick={()=>download('pdf')}/><button className="btn primary full" onClick={()=>download('pptx')}><Download size={14}/> Download PPTX</button><button className="btn secondary full" onClick={()=>download('pdf')}><Download size={14}/> Download PDF</button></>:<div className="fileempty"><Download size={22}/><strong>Files will appear here</strong><p>When status is completed, download the requested outputs.</p></div>}{(job.quality||job.result?.quality)&&<div className="quality"><strong>Quality report <span>{(job.quality||job.result?.quality).score??'—'} score</span></strong><div><b>{(job.quality||job.result?.quality).slide_count??'—'}<small>Slides</small></b><b>{(job.quality||job.result?.quality).fallback_slides??'—'}<small>Fallbacks</small></b><b>{(job.quality||job.result?.quality).validation_errors??'—'}<small>Validation issues</small></b></div></div>}</div></div><div className="panel raw"><PanelHead title="API response" sub="Latest status payload" extra={<button className="icon small" onClick={()=>copy(json(jobResponse||job))}><Copy size={14}/></button>}/><pre className="code">{json(jobResponse||job)}</pre></div></>}{error&&<ErrorBox text={error}/>}</section>}



 {page==='regenerate'&&<section className="enter"><PageTitle eyebrow="STEP 03 · REFINE" title="Regenerate a slide" sub="Improve a specific slide while preserving facts and the deck's intent."/><div className="regen-grid"><form className="panel formpanel" onSubmit={regenerate}><Section n="↻" title="Make a targeted revision" sub="Use an existing presentation as the source."/><Field label="Original presentation job ID" hint="The job ID returned by POST /v1/presentations"><input value={originalId} onChange={e=>setOriginalId(e.target.value)} placeholder={job?.job_id||'e.g. 4890b33e-a6b3-4f98-983d-18e9754720da'}/></Field><div className="fields two"><Field label="Slide ID" hint="Leave blank to regenerate full deck"><input value={slideId} onChange={e=>setSlideId(e.target.value)} placeholder="s2"/></Field><Field label="Revision scope"><div className="scope"><FileText size={16}/><span><strong>{slideId.trim()?'Single slide':'Full presentation'}</strong><small>{slideId.trim()?`Target: ${slideId}`:'All slides will be rebuilt'}</small></span></div></Field></div><Field label="Revision instructions" hint="Describe what should change and what must remain accurate"><textarea rows="5" value={instruction} onChange={e=>setInstruction(e.target.value)} required/></Field><div className="presets"><span>QUICK INSTRUCTIONS</span><div><button type="button" onClick={()=>setInstruction('Shorten the bullet points, improve readability, and retain all source-supported facts.')}>Improve readability</button><button type="button" onClick={()=>setInstruction('Improve chart title, axis labels, legend, and data labels. Do not change the underlying data.')}>Fix chart clarity</button><button type="button" onClick={()=>setInstruction('Improve visual hierarchy and layout consistency. Avoid overlapping text and preserve all factual claims.')}>Improve layout</button></div></div>{error&&<ErrorBox text={error}/>}<button className="btn primary full" type="submit" disabled={regenBusy}>{regenBusy?<LoaderCircle className="spin" size={15}/>:<RefreshCw size={15}/>} Submit regeneration <ArrowRight size={14}/></button></form><aside className="sidecol"><div className="panel"><PanelHead title="Request preview" sub="POST /v1/presentations/{job_id}/regenerate"/><pre className="code">{json({...(slideId.trim()?{slide_id:slideId.trim()}:{}),instruction})}</pre></div><div className="tip"><AlertCircle size={17}/><div><strong>Keep the original job ID</strong><p>Regeneration returns a new job ID. Track the new job in Job monitor.</p></div></div><button className="btn secondary full" onClick={()=>go('monitor')}><Activity size={14}/> Open job monitor</button></aside></div></section>}



 {page==='logs'&&<section className="enter"><PageTitle eyebrow="DEVELOPER TOOLS" title="Request history" sub="Review API calls made from this dashboard." right={<button className="btn quiet" onClick={()=>setLogs([])}><Trash2 size={14}/> Clear history</button>}/><div className="panel"><PanelHead title="Recent requests" sub="Latest 50 requests, newest first. Session memory only." extra={`${logs.length} requests`}/>{logs.length===0?<EmptyEvents title="No requests yet" sub="Run a health check or submit a presentation to see activity."/>:<div className="tablewrap"><table><thead><tr><th>Method</th><th>Endpoint</th><th>Status</th><th>Time</th><th>Details</th></tr></thead><tbody>{logs.map(l=><tr key={l.id}><td><Method method={l.method}/></td><td><code>{l.path}</code></td><td className={String(l.status).startsWith('2')?'good':'bad'}>{l.status}</td><td>{l.time}</td><td>{l.detail}</td></tr>)}</tbody></table></div>}</div></section>}



 {page==='settings'&&<section className="enter"><PageTitle eyebrow="DEVELOPER TOOLS" title="API settings" sub="Configure the backend URL and inspect supported workflow endpoints."/><div className="settingsgrid"><div className="panel formpanel"><PanelHead title="Backend connection" sub="Use an address reachable from this browser." extra={<Globe size={17}/>}/><Field label="FastAPI base URL" hint="No trailing slash required"><input value={base} onChange={e=>setBase(e.target.value)} onBlur={()=>setBase(normalizeApiBase(base))} placeholder="http://localhost:8000"/></Field><div className="settingsactions"><button className="btn primary" onClick={checkHealth} disabled={checking}>{checking?<LoaderCircle className="spin" size={14}/>:<Activity size={14}/>} Test connection</button><button className="btn secondary" onClick={()=>window.open(url(base,'docs'),'_blank')}><ExternalLink size={14}/> Swagger</button><button className="btn secondary" onClick={()=>window.open(url(base,'redoc'),'_blank')}><ExternalLink size={14}/> ReDoc</button></div><div className="connectionrows"><Connection label="FastAPI /health" value={health.api}/><Connection label="Temporal /health/temporal" value={health.temporal}/><Connection label="Redis status" value={health.redis}/></div></div><div className="panel"><PanelHead title="Local service links" sub="Useful during development"/>{[['Swagger UI',url(base,'docs'),Code2],['ReDoc',url(base,'redoc'),FileText],['Temporal UI','http://localhost:8233',Workflow]].map(([label,href,Icon])=><a className="doclink" href={href} target="_blank" rel="noreferrer" key={label}><i><Icon size={17}/></i><span><strong>{label}</strong><small>{href}</small></span><ArrowUpRight size={14}/></a>)}</div></div><div className="panel endpoints"><PanelHead title="Endpoint reference" sub="Paths based on the API workflow you provided." extra="FastAPI"/>{routes.map(r=><Route row={r} key={r[1]} detailed/>)}<div className="note"><AlertCircle size={15}/> Confirm exact endpoint availability and schemas in Swagger; backend versions may differ.</div></div><div className="note blue"><ShieldCheck size={16}/><div><strong>Local development note</strong><p>This UI calls FastAPI from your browser. Allow origin <code>http://localhost:5173</code> in CORS. Do not expose an unauthenticated API publicly.</p></div></div></section>}



 </div><footer><span>© DeckFlow · Local developer workspace</span><span><i className={`dot ${health.api==='ok'?'green':'yellow'}`}/>{health.api==='ok'?'Backend reachable':'Check backend connection'} · API-driven workflow</span></footer></main>{toast&&<div className="toast"><CheckCircle2 size={16}/>{toast}</div>}</div>



}



function Health({title,status,subtitle,icon:Icon,click}){const label=status==='ok'?'Operational':status==='checking'?'Checking':status==='warning'?'Needs review':status==='error'?'Unavailable':'Unknown';return <div className="healthcard"><div className="healthtop"><i><Icon size={17}/></i><span className={`pill ${status}`}><b/> {label}</span></div><h3>{title}</h3><p title={subtitle}>{subtitle}</p>{click&&<button onClick={click}>Open docs <ArrowUpRight size={12}/></button>}</div>}



function Action({icon:Icon,color,step,title,text,foot,click}){return <button className="action" onClick={click}><i className={color}><Icon size={19}/></i><span className="step">{step}<ArrowUpRight size={14}/></span><h3>{title}</h3><p>{text}</p><div className="actionfoot">{foot}<b><ArrowRight size={14}/></b></div></button>}



function PageTitle({eyebrow,title,sub,right}){return <div className="pagetitle"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{sub}</p></div>{right}</div>}



function PanelHead({title,sub,extra}){return <div className="panelhead"><div><h3>{title}</h3>{sub&&<p>{sub}</p>}</div>{extra&&<span className="panel-extra">{extra}</span>}</div>}



function Section({n,title,sub}){return <div className="sectiontitle"><i>{n}</i><div><h3>{title}</h3><p>{sub}</p></div></div>}



function Field({label,hint,children}){return <div className="field"><label>{label}</label>{children}{hint&&<small>{hint}</small>}</div>}



function Method({method}){return <b className={`method ${String(method).toLowerCase()}`}>{method}</b>}



function Route({row,detailed}){return <div className={`route ${detailed?'detailed':''}`}><Method method={row[0]}/><code>{row[1]}</code><span>{row[2]}</span>{detailed&&<button className="icon small" title="Copy endpoint" onClick={()=>navigator.clipboard?.writeText(row[1])}><Copy size={13}/></button>}</div>}



function Status({status}){return <b className={`status ${status}`}>{status.toUpperCase()}</b>}



function ErrorBox({text}){return <div className="errorbox"><AlertCircle size={15}/>{text}</div>}



function EmptyEvents({title='No events received yet',sub='Connect to the event stream to listen for updates.'}){return <div className="empty-events"><MessageSquareText size={22}/><strong>{title}</strong><small>{sub}</small></div>}



function FileRow({ext,title,onClick}){return <button className="filerow" onClick={onClick}><i className={ext.toLowerCase()}>{ext}</i><span><strong>{title}</strong><small>{ext==='PDF'?'Portable document':'Editable PowerPoint file'}</small></span><Download size={15}/></button>}



function Connection({label,value}){return <div className="connection"><span>{label}</span><b className={value==='ok'?'good':value==='checking'?'':'bad'}><i/>{value}</b></div>}



createRoot(document.getElementById('root')).render(<React.StrictMode><App/></React.StrictMode>);


