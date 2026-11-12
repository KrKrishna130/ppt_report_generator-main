"""Editable, reference-inspired PowerPoint compositions.

Uses the existing python-pptx runtime; no new rendering service is required.
All semantic diagrams, labels, tables, charts and metrics remain editable.
"""
import math
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.oxml.ns import qn
from app.services.design import ALIASES, normalize_items

W, H = 13.333, 7.5
ASSETS = Path(__file__).resolve().parent.parent / 'assets' / 'reference'


def rgb(value):
    value = str(value).lstrip('#')
    return RGBColor.from_string(value.upper())


def mix(a, b, fraction):
    a, b = a.lstrip('#'), b.lstrip('#')
    return '#' + ''.join(f'{round(int(a[i:i+2],16)*(1-fraction)+int(b[i:i+2],16)*fraction):02X}' for i in (0,2,4))


class Canvas:
    def __init__(self, slide, theme):
        self.slide, self.t = slide, theme
        self.audit = []
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = rgb(theme['background'])

    def shape(self, kind, x,y,w,h, fill=None, line=None):
        sh = self.slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
        if fill:
            sh.fill.solid(); sh.fill.fore_color.rgb = rgb(fill)
        else:
            sh.fill.background()
        if line:
            sh.line.color.rgb = rgb(line); sh.line.width = Pt(1)
        else:
            sh.line.fill.background()
        sh._element.spPr.append(OxmlElement("a:effectLst"))
        style=sh._element.find(qn("p:style"))
        if style is not None and style.find(qn("a:effectRef")) is not None:
            style.find(qn("a:effectRef")).set("idx", "0")
        if kind == MSO_SHAPE.ROUNDED_RECTANGLE:
            sh.adjustments[0] = 0.07
        return sh

    def box(self,x,y,w,h,fill,line=None):
        return self.shape(MSO_SHAPE.RECTANGLE,x,y,w,h,fill,line)

    def line(self,x1,y1,x2,y2,color=None,width=1):
        s = self.slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1),Inches(y1),Inches(x2),Inches(y2))
        s.line.color.rgb = rgb(color or self.t['primary']); s.line.width = Pt(width)
        s._element.spPr.append(OxmlElement("a:effectLst"))
        style=s._element.find(qn("p:style"))
        if style is not None and style.find(qn("a:effectRef")) is not None:
            style.find(qn("a:effectRef")).set("idx", "0")
        return s

    def text(self,text,x,y,w,h,size=18,color=None,bold=False,font=None,align=PP_ALIGN.LEFT):
        text = str(text or '')
        # Conservative line-width estimate, then allow normal rendering to wrap.
        lines = sum(max(1, math.ceil(len(line) / max(8,w*72/(size*(.65 if bold else .56))))) for line in text.split('\n'))
        fit = min(size, max(12, h*72/max(1,lines)/1.20))
        sh = self.slide.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h))
        tf=sh.text_frame;tf.clear();tf.word_wrap=True
        tf.auto_size=MSO_AUTO_SIZE.NONE
        tf.margin_left=tf.margin_right=Inches(.025)
        tf.margin_top=tf.margin_bottom=Inches(.025)
        for i,line in enumerate(text.split('\n')):
            p=tf.paragraphs[0] if i==0 else tf.add_paragraph();p.text=line
            p.font.name=font or self.t.get('body_font','Liberation Sans')
            p.font.size=Pt(fit);p.font.bold=bold;p.font.color.rgb=rgb(color or self.t['text'])
            p.alignment=align;p.space_after=Pt(5);p.line_spacing=1.08
        if lines*fit*1.20 > h*72:
            self.audit.append('Dense text box: '+text[:70])
        return sh

    def emphasize(self,shape,phrase):
        if not phrase:
            return
        for p in shape.text_frame.paragraphs:
            text=p.text;start=text.casefold().find(str(phrase).casefold())
            if start < 0:
                continue
            p.clear()
            for part,selected in ((text[:start],False),(text[start:start+len(phrase)],True),(text[start+len(phrase):],False)):
                if not part:
                    continue
                run=p.add_run();run.text=part
                if selected:
                    run.font.color.rgb=rgb(self.t.get('accent',self.t['primary']))
                    if self.t.get('design_theme')=='editorial_purple':
                        run.font.italic=True
                    if self.t.get('design_theme')=='india_yellow':
                        run.font.color.rgb=rgb(self.t['text'])
                        highlight=OxmlElement('a:highlight');color=OxmlElement('a:srgbClr')
                        color.set('val',self.t['primary'].lstrip('#'));highlight.append(color)
                        run._r.get_or_add_rPr().append(highlight)

    def heading(self,data,split=False,center=False):
        t=self.t
        if data.get('eyebrow'):
            self.text(data['eyebrow'],.65,.28,11.9,.28,11,t['muted'])
        heading=self.text(data.get('title','Overview'),.65,.76,7.0 if split else 12.0,1.05,
                  30,t['primary'] if t.get('design_theme')=='dark_lime' else t['text'],True,
                  t.get('heading_font'),PP_ALIGN.CENTER if center else PP_ALIGN.LEFT)
        self.emphasize(heading,data.get('emphasis',''))
        self.line(.68,1.94,2.5,1.94,t['primary'],2)
        if data.get('subtitle') or data.get('body'):
            self.text(data.get('subtitle') or data.get('body'),.68,2.08,6.9 if split else 11.9,.68,15,t['muted'])

    def number(self,n,x,y,color=None):
        color=color or self.t['primary']
        self.shape(MSO_SHAPE.OVAL,x,y,.36,.36,color)
        ink='#FFFFFF' if self.t.get('design_theme') in ('editorial_purple','corporate_blue') else '#172028'
        self.text(f'{n:02d}',x+.025,y+.045,.31,.23,10,ink,True,align=PP_ALIGN.CENTER)

    def photo(self,key,x,y,w,h):
        # Keys are fixed server-owned assets. LLM output can never read arbitrary paths.
        path=ASSETS/(key+'.jpg')
        if key not in {'dark_lime','editorial_purple','corporate_blue','india_yellow','chip','workshop','meeting'} or not path.is_file():
            return False
        self.picture(path, x, y, w, h)
        return True

    def picture(self, path, x, y, w, h):
        from PIL import Image
        with Image.open(path) as im: iw,ih=im.size
        picture=self.slide.shapes.add_picture(str(path),Inches(x),Inches(y),width=Inches(w),height=Inches(h))
        target=w/h; actual=iw/ih
        if actual>target:
            crop=(1-target/actual)/2;picture.crop_left=picture.crop_right=crop
        else:
            crop=(1-actual/target)/2;picture.crop_top=picture.crop_bottom=crop


def hero(c,d):
    t=c.t; name=t.get('design_theme')
    key=d.get('image_key') or name
    if t.get("background_match"):
        from app.services.theme_match import image_path
        path = image_path(t["background_match"]["image"])
        if path:
            c.picture(path, 8.1, 0, W - 8.1, H)
        c.text(d.get("eyebrow") or "", .75, 1.55, 6.85, .35, 12, t["muted"])
        c.text(d.get("title", "Presentation"), .75, 2.02, 6.85, 2.2, 36,
               t["text"], True, t.get("heading_font"))
        c.text(d.get("subtitle") or d.get("body") or "", .75, 4.35, 6.85, 1.25,
               16, t["muted"])
        return
    if name=='dark_lime':
        c.photo(key,0,0,8.8,H)
        c.box(7.3,3.15,6.033,4.35,t['background'])
        x,y,w=7.75,3.45,4.9
    elif name=='india_yellow':
        c.box(0,0,W,H,t['primary']);c.photo(key,8,0,5.333,5.7)
        c.line(.65,.6,7.2,.6,t['text'],.7);c.line(.65,0,.65,5.7,t['text'],.7)
        c.box(0,5.75,3.5,1.75,'#111329');x,y,w=.95,2.0,6.5
    elif name=='editorial_purple':
        c.box(0,0,W,H,t['primary']);c.photo(key,8.2,1.1,4.2,5.35)
        x,y,w=.75,2.2,6.7
    else:
        c.photo(key,8.1,0,5.233,H)
        c.shape(MSO_SHAPE.CHEVRON,7.35,0,1.0,H,t['primary'])
        x,y,w=.75,3.65,6.5
    ink='#FFFFFF' if name=='editorial_purple' else (t['primary'] if name=='dark_lime' else t['text'])
    if d.get('eyebrow'):c.text(d['eyebrow'],x,y-.50,w,.35,12,ink)
    c.text(d.get('title','Presentation'),x,y,w,2.2,36,ink,True,t.get('heading_font'))
    c.text(d.get('subtitle') or d.get('body') or '',x,y+2.28,w,.88,16,
           '#E7DCF4' if name=='editorial_purple' else t.get('muted',t['text']))


def numbered(c,d):
    t=c.t;items=normalize_items(d)[:4];has_photo=d.get('image_key') in {'chip','workshop','meeting'}
    if has_photo:c.photo(d['image_key'],9.25,0,4.083,H)
    c.heading(d,split=has_photo)
    width=7.8 if has_photo else 11.8
    if not items:return
    row_h=min(1.0,3.65/len(items));y=2.95
    for i,item in enumerate(items):
        c.number(i+1,.75,y+.08)
        c.text(item['title'],1.3,y,width-.7,.36,18,t['text'],True)
        c.text(item['body'],1.3,y+.40,width-.7,row_h-.42,14,t['muted'])
        y+=row_h


def pillars(c,d):
    c.heading(d,center=True);items=normalize_items(d)[:4];n=len(items)
    if not n:return
    gap=.22;w=(11.9-gap*(n-1))/n
    if c.t.get('design_theme')=='editorial_purple':
        c.shape(MSO_SHAPE.ISOSCELES_TRIANGLE,.7,2.55,11.9,.38,c.t['primary'])
    for i,it in enumerate(items):
        x=.7+i*(w+gap);fill=mix(c.t['primary'],c.t['secondary'],i/max(1,n-1))
        c.box(x+.08,3.12,w-.16,2.98,fill if c.t.get('design_theme')=='dark_lime' else mix(fill,c.t['background'],.87))
        ink='#182529' if c.t.get('design_theme')=='dark_lime' else c.t['text']
        muted=ink if c.t.get('design_theme')=='dark_lime' else c.t['muted']
        c.box(x,2.98,w,.18,fill);c.box(x+.05,3.20,w-.1,.09,fill)
        c.box(x,6.15,w,.18,fill);c.box(x+.05,6.0,w-.1,.09,fill)
        c.text(f'{i+1:02d}',x+.12,3.45,w-.24,.4,17,ink,True,align=PP_ALIGN.CENTER)
        c.text(it['title'],x+.18,4.05,w-.36,.75,20,ink,True,align=PP_ALIGN.CENTER)
        c.text(it['body'],x+.18,4.92,w-.36,.92,14,muted,align=PP_ALIGN.CENTER)


def timeline(c,d):
    c.heading(d);items=d.get('timeline') or normalize_items(d);items=items[:5];n=len(items)
    if n<2:return numbered(c,d)
    c.line(.85,4.55,12.4,4.55,c.t['muted'])
    w=11.55/n
    for i,it in enumerate(items):
        x=.85+i*w
        c.shape(MSO_SHAPE.OVAL,x,4.49,.12,.12,c.t['primary'])
        upper=i%2==1
        y=2.95 if upper else 4.92
        c.text(it.get('date') or f'Stage {i+1}',x,y,w-.25,.36,13,c.t.get('accent',c.t['primary']),True)
        c.text(it.get('title') or it.get('label',''),x,y+.42,w-.25,.58,17,c.t['text'],True)
        c.text(it.get('body',''),x,y+1.02,w-.25,.58,13,c.t['muted'])


def steps(c,d):
    c.heading(d,split=True);items=normalize_items(d)[:4];n=len(items)
    if not n:return
    w=5.9/n
    for i,it in enumerate(items):
        x=6.3+i*w;h=1.05+i*.77;y=6.5-h
        fill=mix(c.t['primary'],c.t['secondary'],i/max(1,n-1))
        c.shape(MSO_SHAPE.CUBE if c.t.get('design_theme')=='dark_lime' and i<n-1 else MSO_SHAPE.UP_ARROW,x,y,w-.12,h,fill)
        c.text(it['title'],.75,3.0+i*.83,5.0,.32,17,c.t['text'],True)
        c.text(it['body'],.75,3.36+i*.83,5.0,.42,13,c.t['muted'])


def pyramid(c,d):
    c.heading(d,center=True);items=normalize_items(d)[:4];n=len(items)
    if not n:return
    for i,it in enumerate(items):
        y=3.0+i*.80;w=1.4+i*1.08;x=6.67-w/2
        fill=mix(c.t['primary'],c.t['secondary'],i/max(1,n-1))
        c.shape(MSO_SHAPE.TRAPEZOID,x,y,w,.72,fill)
        left=i%2==0;tx=.75 if left else 9.25;lx=x if left else x+w
        c.line(lx,y+.35,4.2 if left else 9.05,y+.35,c.t['muted'],.7)
        c.text(it['title'],tx,y-.05,3.25,.40,17,c.t['text'],True)
        c.text(it['body'],tx,y+.38,3.25,.57,13,c.t['muted'])


def radial(c,d,cycle=False):
    c.heading(d,center=True);items=normalize_items(d)[:4]
    if not items:return
    cx,cy=6.67,4.72
    for r in (1.15,1.02):c.shape(MSO_SHAPE.OVAL,cx-r,cy-r,2*r,2*r,None,c.t['primary'])
    c.shape(MSO_SHAPE.OVAL,cx-.88,cy-.88,1.76,1.76,c.t['primary'])
    ink='#FFFFFF' if c.t.get('design_theme') in ('editorial_purple','corporate_blue') else '#172028'
    c.text(d.get('center_label') or ('Continuous\nfeedback' if cycle else 'Unified\nplatform'),cx-.73,cy-.37,1.46,.85,17,ink,True,align=PP_ALIGN.CENTER)
    positions=[(.7,3.05),(9.25,3.05),(.7,5.15),(9.25,5.15)]
    for i,it in enumerate(items):
        x,y=positions[i];left=x<cx
        c.line(x+3.1 if left else x, y+.5,cx-1.1 if left else cx+1.1,cy,c.t['muted'],.8)
        if cycle:
            arrow=c.shape(MSO_SHAPE.CHEVRON,cx-.15,cy-1.43 if i<2 else cy+1.15,.3,.28,c.t['secondary'])
            if i>=2:arrow.rotation=180
        c.number(i+1,x,y)
        c.text(it['title'],x+.48,y,2.65,.49,17,c.t['text'],True)
        c.text(it['body'],x+.02,y+.58,3.15,.90,13,c.t['muted'])


def kpi_split(c,d):
    c.heading(d,split=True);t=c.t;items=normalize_items(d)[:3]
    metrics=[i for i in d.get('kpis',[]) if isinstance(i,dict)][:3]
    right=metrics or items
    for i,it in enumerate(right):
        y=.65+i*2.06;fill=mix(t['primary'],t['secondary'],i/max(1,len(right)-1))
        c.shape(MSO_SHAPE.ROUNDED_RECTANGLE,8.75,y,3.85,1.88,fill)
        ink='#FFFFFF' if t.get('design_theme') in ('corporate_blue','editorial_purple') else '#172028'
        c.text(it.get('value') or it.get('title',''),9.0,y+.20,3.32,.76,30 if it.get('value') else 23,ink,True)
        c.text(it.get('label') or it.get('body',''),9.0,y+1.03,3.32,.61,14,ink)
    left_items=items if metrics else []
    if not metrics:
        c.text(d.get('body') or d.get('subtitle') or '',.75,3.45,7.1,1.35,20,t['muted'])
    for i,it in enumerate(left_items):
        y=3.1+i*1.04;c.number(i+1,.75,y)
        c.text(it['title'],1.3,y,6.65,.35,17,t['text'],True)
        c.text(it['body'],1.3,y+.43,6.65,.49,14,t['muted'])
    c.line(8.4,.65,8.4,6.85,mix(t['text'],t['background'],.8),.7)


def comparison(c,d):
    table=d.get('table')
    if not isinstance(table,dict) or not table.get('headers') or not table.get('rows'):
        return columns(c,d)
    c.heading(d);headers=table['headers'][:5];rows=[r for r in table['rows'][:6] if isinstance(r,list)]
    if not rows:return columns(c,d)
    sh=c.slide.shapes.add_table(len(rows)+1,len(headers),Inches(.7),Inches(2.9),Inches(11.9),Inches(3.70));tab=sh.table
    for ri in range(len(rows)+1):
        for ci in range(len(headers)):
            cell=tab.cell(ri,ci)
            cell.text=str(headers[ci] if ri==0 else (rows[ri-1][ci] if ci<len(rows[ri-1]) else ''))
            cell.margin_left=cell.margin_right=Inches(.12)
            cell.margin_top=cell.margin_bottom=Inches(.09)
            cell.fill.solid();cell.fill.fore_color.rgb=rgb(c.t['surface'] if ri%2==0 else c.t['background'])
            for p in cell.text_frame.paragraphs:
                p.font.name=c.t['body_font'];p.font.size=Pt(13 if ri==0 else 12)
                p.font.bold=ri==0 or ci==0;p.font.color.rgb=rgb(c.t['text'])
    c.line(.7,3.48,12.6,3.48,c.t['primary'],1.5)


def columns(c,d):
    c.heading(d);items=normalize_items(d)
    # Preserve every item rather than silently dropping all but two columns.
    if not items:return
    for i,it in enumerate(items[:6]):
        col=i%2;row=i//2;x=.75+col*6.15;y=2.95+row*1.12
        c.text(it['title'],x,y,5.55,.4,19,c.t.get('accent',c.t['primary']),True)
        c.text(it['body'],x,y+.44,5.55,.64,15,c.t['text'])


def render_designed(slides,theme,resolved,path,options):
    from app.services.render import add_chart, add_matched_background
    prs=Presentation();prs.slide_width=Inches(W);prs.slide_height=Inches(H)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    renderers={'hero':hero,'numbered':numbered,'pillars':pillars,'timeline':timeline,
               'steps':steps,'pyramid':pyramid,'hub':radial,'cycle':lambda c,d:radial(c,d,True),
               'kpi_split':kpi_split,'comparison':comparison,'two_column':columns,'bullets':numbered}
    for i,data in enumerate(slides):
        slide=prs.slides.add_slide(prs.slide_layouts[6]);c=Canvas(slide,theme)
        add_matched_background(slide, theme, W, H)
        layout=ALIASES.get(data.get('layout_variant'),data.get('layout_variant','numbered'))
        if layout=='chart' and isinstance(data.get('chart'),dict):
            c.heading(data)
            if add_chart(slide,data['chart'],theme['primary']):
                chart_shape=next(sh for sh in slide.shapes if sh.has_chart)
                chart_shape.top=Inches(2.9);chart_shape.height=Inches(3.7)
                chart=chart_shape.chart
                for parent in (chart._chartSpace, chart._chartSpace.chart.plotArea):
                    old=parent.find(qn('c:spPr'))
                    if old is not None:parent.remove(old)
                    props=OxmlElement('c:spPr');fill=OxmlElement('a:solidFill')
                    color=OxmlElement('a:srgbClr');color.set('val',theme['background'].lstrip('#'))
                    fill.append(color);props.append(fill)
                    line=OxmlElement('a:ln');line.append(OxmlElement('a:noFill'));props.append(line)
                    parent.append(props)
                for p in chart.chart_title.text_frame.paragraphs:
                    p.font.color.rgb=rgb(theme['text'])
                if chart.has_legend:
                    chart.legend.font.name=theme['body_font'];chart.legend.font.size=Pt(13)
                    chart.legend.font.color.rgb=rgb(theme['text'])
                try:
                    for axis in (chart.category_axis,chart.value_axis):
                        axis.tick_labels.font.name=theme['body_font'];axis.tick_labels.font.size=Pt(12)
                        axis.tick_labels.font.color.rgb=rgb(theme['text'])
                    chart.value_axis.major_gridlines.format.line.color.rgb=rgb(theme['surface'])
                except ValueError:
                    pass
                for series in chart.series:
                    series.format.fill.solid();series.format.fill.fore_color.rgb=rgb(theme['primary'])
                    series.format.line.color.rgb=rgb(theme['primary'])
                    if str(data['chart'].get('type')).lower()=='pie':
                        for j,point in enumerate(series.points):
                            point.format.fill.solid()
                            point.format.fill.fore_color.rgb=rgb(mix(theme['primary'],theme['secondary'],j/max(1,len(series.points)-1)))
            else:numbered(c,data)
        else:renderers.get(layout,numbered)(c,data)
        footer_color=theme['muted']
        if layout=='hero' and theme.get('design_theme')=='editorial_purple' and not theme.get('background_match'):footer_color='#E7DCF4'
        c.text(f'{i+1:02d} / {len(slides):02d}',11.7,7.13,.88,.21,9,footer_color,align=PP_ALIGN.RIGHT)
        # Preserve complete structured content as notes for editing and QA.
        notes=data.get('speaker_notes','')
        if options.get('speaker_notes',True):
            import json
            slide.notes_slide.notes_text_frame.text=notes+'\n\nContent record:\n'+json.dumps(data,ensure_ascii=False,indent=2)
        if c.audit:
            data.setdefault('render_warnings',[]).extend(c.audit)
    prs.core_properties.title=str(slides[0].get('title','Presentation')) if slides else 'Presentation'
    prs.core_properties.subject='Reference-inspired editable presentation'
    prs.save(str(path));return path
