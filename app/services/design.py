"""Reference-inspired deck themes and deterministic semantic layout selection.

Themes and render metadata are plain JSON, so they remain compatible with Temporal and stored manifests.
"""
import re

THEMES = {
    'dark_lime': dict(background='#050910', text='#F5F7F8', primary='#B8EF58', secondary='#80E8C4', surface='#152322', muted='#B6C1C7', heading_font='Liberation Sans', body_font='Liberation Sans'),
    'editorial_purple': dict(background='#FAF9F6', text='#201936', primary='#402083', secondary='#8D5CB7', surface='#EBE6F0', muted='#645D70', heading_font='Liberation Serif', body_font='Liberation Sans'),
    'corporate_blue': dict(background='#F8FAFF', text='#172236', primary='#193CEB', secondary='#479FDD', surface='#E7ECFF', muted='#606C7C', heading_font='Liberation Sans', body_font='Liberation Sans'),
    'india_yellow': dict(background='#FAFAF7', text='#191C2C', primary='#F2C43D', secondary='#EBA23E', surface='#FFF2BA', muted='#626366', heading_font='Liberation Sans', body_font='Liberation Sans'),
}
LAYOUTS = ('hero', 'numbered', 'pillars', 'timeline', 'steps', 'pyramid',
           'hub', 'cycle', 'kpi_split', 'comparison', 'two_column', 'bullets', 'chart')
ALIASES = {'title':'hero', 'table':'comparison', 'kpi':'kpi_split', 'process':'steps', 'cards':'numbered'}


def infer_theme(text):
    text = str(text).casefold()
    if any(x in text for x in ('battlecard', 'competitive sales', 'competitor', 'playbook')):
        return 'editorial_purple'
    if any(x in text for x in ('unified', 'mid-market', 'sales pitch', 'operations platform')):
        return 'corporate_blue'
    if any(x in text for x in ('evolution', 'trajectory', 'foundation model', 'transformer')):
        return 'dark_lime'
    if any(x in text for x in ('india', 'indian', 'bharat')):
        return 'india_yellow'
    return 'corporate_blue'


def apply_theme(theme, options, text):
    selected = options.get('design_theme') or 'auto'
    selected = infer_theme(text) if selected == 'auto' else selected
    if selected == 'legacy':
        return theme
    # Respect legacy callers explicitly selecting an existing color/style.
    explicit = options.get('design_theme') not in (None, 'auto')
    if not explicit and (options.get('theme') or options.get('theme_style')):
        selected = 'custom'
    if selected in THEMES:
        theme.update(THEMES[selected])
    else:
        dark = theme.get('theme_style') == 'dark'
        theme.update(surface='#1E293B' if dark else '#EEF2F8',
                     muted='#CBD5E1' if dark else '#536174',
                     heading_font='Liberation Sans', body_font='Liberation Sans')
    font = options.get('font')
    if font:
        theme.update(heading_font=font, body_font=font)
    colors = options.get('brand_colors') or []
    if colors:
        theme['primary'] = colors[0]
        if len(colors) > 1:
            theme['secondary'] = colors[1]
    theme['accent'] = '#805E00' if selected == 'india_yellow' else theme['primary']
    theme.update(design_theme=selected, design_version=2)
    return theme


def choose_layout(item, index, total):
    if index == 0:
        return 'hero'
    requested = str(item.get('layout_variant', '')).lower()
    requested = ALIASES.get(requested, requested)
    title = str(item.get('key_message') or item.get('title') or '').lower()
    visual = str(item.get('visual_type', '')).lower()
    # Content semantics beat an undifferentiated bullets response from a small LLM.
    if re.search(r'compar|versus|\bvs\b|objection|archetype|alternatives', title) or visual == 'table':
        return 'comparison'
    if re.search(r'cycle|feedback|attention|loop', title):
        return 'cycle'
    if re.search(r'histor|evolution|roadmap|rollout|stages|eras', title) or visual == 'timeline':
        return 'timeline'
    if re.search(r'pillar|frontier|foundation of|value driver', title):
        return 'pillars'
    if re.search(r'layer|hierarchy|stack|ecosystem', title):
        return 'pyramid'
    if re.search(r'platform engine|hub|multimodal|language inclusion', title):
        return 'hub'
    if re.search(r'growth|depth|scale|progression', title):
        return 'steps'
    if re.search(r'impact|mission|roi|result|case study|retention|throughput', title) or visual == 'kpi':
        return 'kpi_split'
    if visual == 'chart':
        return 'chart'
    if requested in LAYOUTS and requested != 'bullets':
        return requested
    if index == total - 1:
        return 'numbered'
    return ('numbered', 'two_column', 'pillars', 'hub')[((index - 1) % 4)]


def normalize_items(data):
    raw = data.get('items')
    if not isinstance(raw, list) or not raw:
        raw = data.get('columns') or data.get('bullets') or []
    result = []
    for entry in raw[:6]:
        if isinstance(entry, dict):
            title = entry.get('title') or entry.get('label') or ''
            body = entry.get('body') or entry.get('description') or ''
            if not body and isinstance(entry.get('bullets'), list):
                body = '\n'.join(map(str, entry['bullets']))
        else:
            value = str(entry)
            title, sep, body = value.partition(':')
            if not sep:
                title, body = '', value
        if str(title).strip() or str(body).strip():
            result.append({'title':str(title).strip(), 'body':str(body).strip()})
    return result


def finalize_slide(data, planned):
    data['layout_variant'] = planned.get('layout_variant', data.get('layout_variant', 'numbered'))
    data['items'] = normalize_items(data)
    for field in ('eyebrow', 'subtitle', 'center_label', 'image_key'):
        value = data.get(field, '')
        data[field] = str(value) if value is not None else ''
    return data
