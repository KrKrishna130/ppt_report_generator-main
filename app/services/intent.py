"""Deterministic explicit instructions; structured options always take priority."""
import re

COLORS = {'navy blue':'navy', 'deep navy blue':'navy', 'emerald green':'emerald',
          'forest green':'forest', 'electric blue':'electric', 'matrix green':'neon',
          'neon green':'neon', 'crimson red':'crimson', 'burgundy':'burgundy',
          'oxford blue':'navy', 'red':'red', 'blue':'blue', 'green':'green',
          'orange':'orange', 'purple':'purple', 'teal':'teal', 'cyan':'cyan',
          'olive':'olive', 'crimson':'crimson', 'navy':'navy'}

def explicit_intent(prompt):
    text = str(prompt or '').lower()
    result = {}
    counts = list(re.finditer(r'\b(\d{1,3})\s*[- ]?slides?\b|\bslides?\s*(?:count\s*)?(?:[:=]|is)?\s*(\d{1,3})\b', text))
    if counts:
        m = counts[-1]
        result['slide_count'] = int(m.group(1) or m.group(2))
    names = '|'.join(re.escape(c) for c in sorted(COLORS, key=len, reverse=True))
    matches = list(re.finditer(r'(?:\b(?:colou?r|theme|palette)\s*(?:is|:|=|of|in)?\s*|\buse\s+)(' + names + r')\b|\b(' + names + r')\s+(?:colou?r|theme|palette)\b', text))
    if matches:
        result['theme_color'] = COLORS[matches[-1].group(1) or matches[-1].group(2)]
    if re.search(r'\b(?:without|no|disable|omit)\s+(?:speaker\s+)?notes\b', text):
        result['speaker_notes'] = False
    elif re.search(r'\b(?:with|include|enable|add)\s+(?:speaker\s+)?notes\b', text):
        result['speaker_notes'] = True
    if re.search(r'\b(?:use|from|based on|summari[sz]e)\s+(?:the\s+)?(?:provided|supplied|attached|source)\s+(?:text|content|material|document)', text):
        result['content_mode'] = 'source'
    if re.search(r'\bdark\s+(?:theme|background|mode)\b', text):
        result['theme_style'] = 'dark'
    return result


def domain_color(text):
    rules = [
        (r'cyber|cybersecurity|digital security', 'electric'),
        (r'terror|danger|emergency|hazard|high risk', 'crimson'),
        (r'constitution|legal|legislation|\bact\b|\blaw\b', 'burgundy'),
        (r'bank|finance|financial|corporate|authority', 'navy'),
        (r'environment|sustainab|ecolog|nature', 'forest'),
        (r'water|aquatic|ocean', 'teal'),
        (r'education|academic|university|school', 'navy'),
    ]
    return next((color for pattern, color in rules if re.search(pattern, text, re.I)), None)
