"""
Presentation generation pipeline.

Compatible with the existing Temporal activities:
source_adapter, parse_prompt, resolve, plan, build, validate, review.

The pipeline keeps facts source-grounded and adds text normalization and
stronger validation to reduce malformed slide text.
"""
import asyncio
import hashlib
import json
import logging
import math
import random
import re
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.services.intent import explicit_intent, domain_color
try:
    from redis.asyncio import Redis
except ImportError:  # Allows pure unit tests without the optional runtime dependencies installed.
    Redis = None
from app.services.llm import chat, parse_json
from app.services.render import render_pptx, render_pdf, render_thumbnails
from app.services.design import apply_theme, choose_layout, finalize_slide, LAYOUTS

log = logging.getLogger(__name__)
_digest_cache = Redis.from_url(settings.redis_url, decode_responses=True) if Redis else None

PALETTES = {
    "navy": ["#142D4E", "#52799D", "#142D4E", "#E6EDF4"],
    "emerald": ["#047857", "#34D399", "#064E3B", "#D1FAE5"],
    "burgundy": ["#800020", "#B45C74", "#500016", "#F8E8ED"],
    "crimson": ["#B91C3C", "#EF7187", "#710D24", "#FDE9EE"],
    "forest": ["#166534", "#6BA67B", "#14532D", "#E8F5E9"],
    "olive": ["#596329", "#A7B46B", "#3F471B", "#F0F2DF"],
    "cyan": ["#087F8C", "#67E8F9", "#164E63", "#CFFAFE"],
    "electric": ["#38BDF8", "#22D3EE", "#082F49", "#CFFAFE"],
    "neon": ["#4ADE80", "#A3E635", "#14532D", "#DCFCE7"],
    "blue": ["#1D4ED8", "#60A5FA", "#0F172A", "#DBEAFE"],
    "red": ["#DC2626", "#FCA5A5", "#7F1D1D", "#FEE2E2"],
    "orange": ["#EA580C", "#FDBA74", "#7C2D12", "#FFEDD5"],
    "green": ["#15803D", "#4ADE80", "#14532D", "#DCFCE7"],
    "purple": ["#7C3AED", "#C4B5FD", "#4C1D95", "#EDE9FE"],
    "teal": ["#0F766E", "#5EEAD5", "#134E4A", "#CCFBF1"],
    "dark": ["#0F172A", "#64748B", "#F8FAFC", "#E2E8F0"],
}


# ---------------------------------------------------------------------
# Text and JSON utilities
# ---------------------------------------------------------------------

def clean_text(value):
    """Normalize whitespace but do not join or rewrite words."""
    if value is None:
        return ""
    value = str(value).replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def safe_json(value):
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return "{}"


def chunks(text, size):
    text = str(text or "")
    size = max(1, int(size))
    out, current = [], ""

    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) > size:
            if current:
                out.append(current)
                current = ""
            out.extend(para[i:i + size] for i in range(0, len(para), size))
        elif current and len(current) + len(para) + 2 > size:
            out.append(current)
            current = para
        else:
            current = (current + "\n\n" + para).strip()

    if current:
        out.append(current)
    return out or [text[:size] or "No source content provided."]


def normalize_topic(topic, index=0):
    """Accept either topic objects or strings returned by an LLM."""
    if isinstance(topic, dict):
        title = clean_text(topic.get("title") or topic.get("name") or f"Section {index + 1}")
        summary = clean_text(topic.get("summary") or topic.get("description") or topic.get("content") or "")
        quote = clean_text(topic.get("source_quote") or summary[:250])
        return {
            **topic,
            "title": title[:200] or f"Section {index + 1}",
            "summary": summary[:2000],
            "source_quote": quote[:500],
        }

    value = clean_text(topic) or f"Section {index + 1}"
    return {"title": value[:200], "summary": value[:2000], "source_quote": value[:500]}


def normalize_topics(topics):
    if not isinstance(topics, list):
        topics = []
    result = [normalize_topic(item, i) for i, item in enumerate(topics)]
    result = [item for item in result if item.get("title", "").strip()]
    return result or [{
        "title": "Overview",
        "summary": "Summarize the provided source material.",
        "source_quote": "",
    }]


def parse_llm_json(raw, expected_type=dict):
    parsed = parse_json(raw)
    if not isinstance(parsed, expected_type):
        raise ValueError(f"Expected {expected_type.__name__} from LLM")
    return parsed


# ---------------------------------------------------------------------
# Source processing
# ---------------------------------------------------------------------

def source_text(source):
    source = source or {}
    source_type = source.get("type", "plain")

    if source_type == "plain":
        return clean_text(source.get("content") or ""), []

    messages, seen = [], set()
    for message in source.get("messages") or []:
        if not isinstance(message, dict):
            continue
        content = clean_text(message.get("content") or "")
        role = message.get("role", "user")
        if not content:
            continue
        if content.lower() in {
            "ok", "okay", "thanks", "thank you", "hi", "hello", "great", "sure"
        }:
            continue
        identity = (role, content)
        if identity in seen:
            continue
        seen.add(identity)
        messages.append({**message, "content": content, "role": role})

    text = "\n".join(
        f"[{message.get('id', '')}] {message.get('role', 'user')}: {message.get('content', '')}"
        for message in messages
    )
    return text, messages


async def digest(chunk, index):
    cache_key = "pptdigest:" + hashlib.sha256(chunk.encode("utf-8")).hexdigest()
    if _digest_cache is not None:
        try:
            cached = await _digest_cache.get(cache_key)
            if cached:
                result = json.loads(cached)
                result["topics"] = normalize_topics(result.get("topics"))
                return result
        except Exception as exc:
            log.debug("Digest cache read skipped: %s", exc)
    prompt = f"""
Extract source-grounded JSON with these keys:
topics, facts, numbers, dates, decisions, actions,
open_questions, visual_signals, domain, register, language.

topics must be a list. Each topic should preferably be an object with
title, summary, and source_quote. source_quote must be copied verbatim from
the input chunk, or be an empty string if no short exact quote is available.

Do not invent facts, dates, statistics, or quotations.
Return valid JSON only.

CHUNK {index + 1}:
{chunk}
"""
    try:
        response = await chat(
            "gemma",
            "Extract facts faithfully. Return valid JSON only.",
            prompt,
            max_tokens=settings.digest_max_tokens,
        )
        result = parse_llm_json(response)
        result["topics"] = normalize_topics(result.get("topics"))
        if _digest_cache is not None:
            try:
                await _digest_cache.setex(cache_key, settings.job_ttl_hours * 3600, json.dumps(result, ensure_ascii=False))
            except Exception as exc:
                log.debug("Digest cache write skipped: %s", exc)
        return result
    except Exception as exc:
        log.warning("Digest fallback for chunk %s: %s", index + 1, exc)
        return {
            "topics": [{
                "title": f"Section {index + 1}",
                "summary": chunk[:500],
                "source_quote": chunk[:250],
            }],
            "warnings": [f"Digest fallback used for chunk {index + 1}: {exc}"],
        }


async def draft_topic_pack(source):
    """Explicit topic mode: AI knowledge is a draft, never a verified source."""
    query = clean_text(source.get("_query") or source.get("content"))
    if not query or len(query) > settings.max_input_chars:
        raise ValueError("Topic query is empty or exceeds MAX_INPUT_CHARS")
    raw = await chat(
        "gemma", "Draft a coherent presentation research brief as JSON only.",
        f"""Topic: {query}
Return {{"topics":[{{"title":"...","summary":"..."}}]}}.
Provide 10 distinct, useful topics with 60 to 100 words per summary.
Cover the requested subject, its context, mechanisms, applications and next steps.
For a sales pitch cover problems, capabilities, differentiation, proof needed and rollout.
For a battlecard cover positioning, rival archetypes, discovery, objections and closing.
Use general established knowledge only. Do not invent company results, customer names,
quotations, funding, statistics, current policy details or dates. Mark proposed business
benefits as hypotheses. Do not claim to have searched the web. Avoid repeated sections.
""", max_tokens=max(settings.planner_max_tokens, 5000))
    data = parse_llm_json(raw)
    if not isinstance(data.get("topics"), list) or len(data["topics"]) < 4:
        raise ValueError("Topic drafting returned too few topics; retry with a more specific query")
    topics = normalize_topics(data["topics"])
    for topic in topics:
        topic["source_quote"] = ""
    text = "\n\n".join(t["title"] + "\n" + t["summary"] for t in topics)
    return {"topics":topics, "source_text":text, "source_messages":[],
            "content_mode":"topic", "domain":"general", "language":"en",
            "warnings":["Topic mode uses AI general knowledge. It is not live research or independently verified evidence. Review facts before presenting."]}


async def source_adapter(source):
    if (source or {}).get("_content_mode") == "topic":
        return await draft_topic_pack(source)
    text, messages = source_text(source)
    if not text.strip():
        raise ValueError("Source text is empty.")
    if len(text) > settings.max_input_chars:
        raise ValueError(f"Input exceeds MAX_INPUT_CHARS={settings.max_input_chars}")

    source_chunks = chunks(text, settings.chunk_tokens * 4)
    digests = await asyncio.gather(*[
        digest(chunk, index) for index, chunk in enumerate(source_chunks)
    ])

    list_keys = [
        "topics", "facts", "numbers", "dates", "decisions",
        "actions", "open_questions", "visual_signals", "warnings",
    ]
    pack = {key: [] for key in list_keys}

    for result in digests:
        for key in list_keys:
            value = result.get(key, [])
            if isinstance(value, list):
                pack[key].extend(value)
        for key in ("domain", "register", "language"):
            if not pack.get(key) and result.get(key):
                pack[key] = result[key]

    # Prevent "'str' object has no attribute 'get'" in downstream planning.
    pack["topics"] = normalize_topics(pack.get("topics"))
    pack["topics"] = pack["topics"][:settings.max_output_slides]
    pack["source_text"] = text
    pack["source_messages"] = messages
    return pack


# ---------------------------------------------------------------------
# Prompt parsing and setting resolution
# ---------------------------------------------------------------------

async def parse_prompt(prompt):
    prompt = clean_text(prompt)
    if not prompt:
        return {}

    try:
        response = await chat(
            "gemma",
            "Extract only explicitly stated presentation settings. Return valid JSON only.",
            f"""
Return JSON keys:
slide_count, audience, tone, visuals_required, theme_color,
theme_style, language, must_include, must_avoid.

Use null or empty lists for unknown values. Do not invent preferences.

Prompt:
{prompt}
""",
            max_tokens=settings.parser_max_tokens,
        )
        result = parse_llm_json(response)
        result.update(explicit_intent(prompt))
        return result
    except Exception as exc:
        log.warning("Prompt parsing fallback: %s", exc)
        result = {}
        match = re.search(r"\b(\d{1,2})\s*[- ]?slides?\b", prompt, re.I)
        if match:
            result["slide_count"] = int(match.group(1))
        for color in PALETTES:
            if re.search(rf"\b{re.escape(color)}\b", prompt, re.I):
                result["theme_color"] = color
                break
        result.update(explicit_intent(prompt))
        return result


def _hex_luminance(value):
    value = str(value or "#000000").lstrip("#")
    if len(value) != 6:
        return 0.0
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    channels = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(a, b):
    la, lb = _hex_luminance(a), _hex_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _accessible_foreground(color, background, minimum):
    if _contrast_ratio(color, background) >= minimum:
        return color
    candidates = ["#FFFFFF", "#000000", "#F8FAFC", "#0F172A"]
    return max(candidates, key=lambda candidate: _contrast_ratio(candidate, background))


def resolve(options, parsed, pack, prompt):
    options = options or {}
    parsed = {**(parsed or {}), **explicit_intent(prompt)}
    prompt = clean_text(prompt)
    topics = normalize_topics((pack or {}).get("topics"))

    semantic_color = domain_color(prompt + " " + (pack or {}).get("source_text", "")[:2000])
    inferred_color = semantic_color or "blue"
    inferred = {
        "slide_count": min(max(len(topics) + 2, settings.slides_min), settings.slides_max),
        "tone": (pack or {}).get("register") or "general",
        "audience": "general",
        "visuals_required": (pack or {}).get("visual_signals") or [],
        "language": (pack or {}).get("language") or "en",
        "theme_color": inferred_color,
        "theme_style": "dark" if re.search(r"\bdark\b", prompt, re.I) else "clean",
    }
    defaults = {
        "slide_count": settings.default_slide_count,
        "tone": "general",
        "audience": "general",
        "visuals_required": [],
        "language": "en",
        "theme_color": "blue",
        "theme_style": "clean",
    }

    resolved = {}
    for key, default in defaults.items():
        option_key = "theme" if key == "theme_color" else key
        option_value = options.get(option_key)
        prompt_value = parsed.get(key)
        inferred_value = inferred.get(key)

        if option_value not in (None, "", []):
            value, source = option_value, "options"
        elif prompt_value not in (None, "", []):
            value, source = prompt_value, "prompt"
        elif inferred_value not in (None, "", []):
            value, source = inferred_value, "inferred"
        else:
            value, source = default, "config"
        resolved[key] = {"value": value, "source": source}

    try:
        slide_count = int(resolved["slide_count"]["value"])
    except (TypeError, ValueError):
        slide_count = settings.default_slide_count
    minimum = max(1, settings.slides_min)
    maximum = max(minimum, min(settings.slides_max, settings.max_output_slides))
    resolved["slide_count"]["value"] = max(minimum, min(slide_count, maximum))

    seed = options.get("seed")
    if seed is None:
        seed = random.randint(1, 999999)
    resolved["seed"] = {
        "value": seed,
        "source": "options" if options.get("seed") is not None else "random",
    }

    color = str(resolved["theme_color"]["value"]).lower().strip()
    palette = PALETTES.get(color, PALETTES["blue"])
    style = str(resolved["theme_style"]["value"]).lower().strip()
    is_dark = style == "dark"
    background = "#0B1220" if is_dark else "#FFFFFF"
    primary = "#93C5FD" if is_dark and color == "blue" else palette[0]
    primary = _accessible_foreground(primary, background, settings.min_contrast)
    theme = {
        "name": color if color in PALETTES else "blue",
        "primary": primary,
        "secondary": "#475569" if is_dark else palette[1],
        "text": "#F8FAFC" if is_dark else "#0F172A",
        "light": "#1E293B" if is_dark else "#FFFFFF",
        "background": background,
        "theme_style": "dark" if is_dark else "clean",
        "palette": palette,
        "seed": int(resolved["seed"]["value"]),
        "title_style": random.Random(int(resolved["seed"]["value"])).choice(["left", "center"]),
    }
    resolved["content_mode"] = {"value": options.get("content_mode", "source"), "source": "options"}
    effective_options = dict(options)
    if not options.get('theme') and (parsed.get('theme_color') or semantic_color):
        effective_options['theme'] = color
    if not options.get('theme_style') and style == 'dark':
        effective_options['theme_style'] = style
    theme = apply_theme(theme, effective_options, prompt + " " + (pack or {}).get("source_text", "")[:1000])
    return resolved, theme


# ---------------------------------------------------------------------
# Outline planner
# ---------------------------------------------------------------------

def fallback_outline(pack, slide_count):
    topics = normalize_topics((pack or {}).get("topics"))
    result = []
    for index in range(slide_count):
        if index == 0:
            topic_index, layout = 0, "title"
        elif index == slide_count - 1:
            topic_index, layout = len(topics) - 1, "bullets"
        else:
            topic_index, layout = (index - 1) % len(topics), "bullets"
        topic = topics[topic_index]
        result.append({
            "id": f"s{index + 1}",
            "section": topic["title"],
            "key_message": topic["title"],
            "visual_type": "text",
            "layout_variant": layout,
            "topic_refs": [topic_index],
        })
    for i, item in enumerate(result):
        item["layout_variant"] = choose_layout(item, i, len(result))
    return result


async def plan(pack, resolved, prompt):
    topics = normalize_topics((pack or {}).get("topics"))
    pack["topics"] = topics
    slide_count = int(resolved["slide_count"]["value"])

    user_prompt = f"""
Return valid JSON:
{{
  "slides": [
    {{
      "id": "s1",
      "section": "Section",
      "key_message": "Short slide title",
      "visual_type": "text|chart|timeline|process|table|kpi",
      "layout_variant": "hero|numbered|pillars|timeline|steps|pyramid|hub|cycle|kpi_split|comparison|two_column|chart",
      "topic_refs": [0]
    }}
  ]
}}

Return exactly {slide_count} slides.
Use valid topic_refs indexes from 0 to {len(topics) - 1}.
Include an introduction and a conclusion.
Choose a composition that expresses the content, rather than repeating bullet slides.
Use pillars for 3-4 principles, a pyramid for layers, hub for connected capabilities,
cycle for feedback, timeline for stages/history, comparison for tables,
kpi_split only for evidence-backed metrics, numbered for recommendations.
Vary adjacent compositions. The first slide must use hero.
Use only source-supported topics. Do not invent facts or statistics.

User prompt:
{prompt}

Settings:
{safe_json(resolved)}

Topics:
{safe_json(topics)[:14000]}
"""
    try:
        # Gemma is used here because the previously configured GLM endpoint
        # was returning HTTP 404 in this project.
        response = await chat(
            "gemma",
            "Plan a source-grounded presentation. Return valid JSON only.",
            user_prompt,
            temperature=settings.planner_temperature,
            max_tokens=settings.planner_max_tokens,
        )
        parsed = parse_llm_json(response)
        raw_slides = parsed.get("slides", [])
        if not isinstance(raw_slides, list):
            raise ValueError("Planner 'slides' must be a list")

        valid = []
        for slide in raw_slides:
            if not isinstance(slide, dict):
                continue
            refs = slide.get("topic_refs", [])
            if not isinstance(refs, list):
                refs = []
            refs = [
                ref for ref in refs
                if isinstance(ref, int) and not isinstance(ref, bool)
                and 0 <= ref < len(topics)
            ]
            slide["topic_refs"] = refs or [len(valid) % len(topics)]
            valid.append(slide)

        fallback = fallback_outline(pack, slide_count)
        valid = valid[:slide_count]
        while len(valid) < slide_count:
            valid.append(fallback[len(valid)])

        for index, slide in enumerate(valid):
            slide.setdefault("id", f"s{index + 1}")
            topic = topics[slide["topic_refs"][0]]
            slide.setdefault("section", topic["title"])
            slide.setdefault("key_message", topic["title"])
            slide.setdefault("visual_type", "text")
            slide["layout_variant"] = choose_layout(slide, index, slide_count)
        return valid
    except Exception:
        log.exception("Planner failed; using deterministic outline")
        return fallback_outline(pack, slide_count)


# ---------------------------------------------------------------------
# Slide builder and validation
# ---------------------------------------------------------------------

async def build(slide, pack, prompt, theme, feedback=""):
    topics = normalize_topics((pack or {}).get("topics"))
    refs = slide.get("topic_refs", [])
    evidence = [
        topics[index] for index in refs
        if isinstance(index, int) and not isinstance(index, bool)
        and 0 <= index < len(topics)
    ]
    if not evidence:
        evidence = [topics[0]]

    user_prompt = f"""
Return valid JSON with these keys:
title, bullets, body, visual_type, layout_variant, chart, timeline,
table, kpis, columns, items, eyebrow, subtitle, emphasis, center_label, image_key,
speaker_notes, source_quotes.
items: list of 2 to 4 objects, each with title (max 6 words) and body (max 22 words).
Every non-cover diagram/numbered slide needs items. Use items that describe the actual subject.
emphasis: optional 2-4 word phrase copied exactly from title to highlight.
eyebrow: optional short section label. subtitle: one short sentence, max 22 words.
center_label: max 3 words for hub/cycle diagrams.
image_key: empty, chip (hardware only), workshop (collaboration only), meeting (sales only).
Follow the outline's layout_variant exactly. A hero needs title and subtitle.
Timeline needs 3-5 events with date, label and body. Use stage labels if no dates exist.
Comparison needs a table only when source supports an actual comparison.
Use source-backed KPI values only. If none exist, supply items instead.
Do not put arbitrary images on diagram slides.
Keep headings under 12 words and at most 85 characters.
table: null or {{"headers":["..."],"rows":[["..."]]}}.
kpis: list of {{"label":"...","value":"..."}}.
columns: list of {{"title":"...","body":"...","bullets":["..."]}}.
Only use table/KPI/column content supported by evidence.

TEXT QUALITY REQUIREMENTS:
- Write correctly spelled, natural English words.
- Never insert spaces inside words for visual formatting.
- Use one space between adjacent words.
- Keep titles concise and grammatically correct.
- Use complete sentences and normal punctuation.
- Do not add Markdown markers to slide text.
- Keep bullet points short enough to fit on one slide.
- Keep chart titles and labels short and readable.
- Do not repeat the same information unnecessarily.
- Do not invent facts, statistics, or source quotations.

Chart format:
{{"type":"bar|line|pie","title":"Chart title",
  "labels":["A","B"],"values":[1,2]}}

Only create a chart if evidence contains the values. Otherwise set chart to null.
Return valid JSON only.

Slide:
{safe_json(slide)}

Evidence:
{safe_json(evidence)}

Prompt:
{prompt}

Theme:
{safe_json(theme)}

Validation feedback:
{feedback}
"""
    try:
        response = await chat(
            "gemma",
            "Write one source-grounded slide as valid JSON. Return JSON only.",
            user_prompt,
            temperature=settings.builder_temperature,
            max_tokens=settings.builder_max_tokens,
        )
        data = parse_llm_json(response)
    except Exception as exc:
        log.warning("Slide builder fallback for %s: %s", slide.get("id"), exc)
        topic = evidence[0]
        data = {
            "title": slide.get("key_message", topic["title"]),
            "bullets": [topic.get("summary") or topic["title"]],
            "body": "",
            "visual_type": slide.get("visual_type", "text"),
            "chart": None,
            "timeline": [],
            "speaker_notes": "",
            "source_quotes": [topic.get("source_quote", "")],
            "warnings": [str(exc)],
        }

    data["id"] = slide.get("id", "s1")
    data["section"] = slide.get("section", "")
    data["visual_type"] = slide.get("visual_type", data.get("visual_type", "text"))
    data["layout_variant"] = slide.get("layout_variant", data.get("layout_variant", "bullets"))
    data["table"] = data.get("table") if isinstance(data.get("table"), dict) else None
    data["kpis"] = data.get("kpis") if isinstance(data.get("kpis"), list) else []
    data["columns"] = data.get("columns") if isinstance(data.get("columns"), list) else []
    data["title"] = clean_text(
        data.get("title") or slide.get("key_message") or "Overview"
    )[:110]

    bullets = data.get("bullets", [])
    if not isinstance(bullets, list):
        bullets = [bullets] if bullets else []
    data["bullets"] = [clean_text(item)[:240] for item in bullets[:5] if clean_text(item)]
    data["body"] = clean_text(data.get("body", ""))[:1200]
    data["speaker_notes"] = clean_text(data.get("speaker_notes", ""))[:2000]

    timeline = data.get("timeline", [])
    if not isinstance(timeline, list):
        timeline = []
    data["timeline"] = [
        {
            "date": clean_text(item.get("date", ""))[:40],
            "label": clean_text(item.get("label", ""))[:100],
        }
        for item in timeline[:6] if isinstance(item, dict)
    ]

    data = finalize_slide(data, slide)
    if pack.get("content_mode") == "topic":
        data["speaker_notes"] = "AI-drafted topic content, not live or independently verified research.\n" + data["speaker_notes"]

    # Normalize chart schema. Invalid chart data is removed instead of
    # causing PowerPoint generation to fail.
    chart = data.get("chart")
    if isinstance(chart, dict):
        labels, values = chart.get("labels"), chart.get("values")
        if not isinstance(labels, list) or not isinstance(values, list) or len(labels) != len(values) or len(labels) < 2:
            data["chart"] = None
        else:
            try:
                numeric = [float(value) for value in values]
                if not all(value == value and abs(value) != float("inf") for value in numeric):
                    raise ValueError("Non-finite chart value")
                data["chart"] = {
                    "type": str(chart.get("type", "bar")).lower(),
                    "title": clean_text(chart.get("title", "Chart"))[:100],
                    "labels": [clean_text(label)[:60] for label in labels],
                    "values": numeric,
                }
            except (TypeError, ValueError, OverflowError):
                data["chart"] = None
    else:
        data["chart"] = None

    return data


def _number_tokens(text):
    """Extract numeric tokens while treating comma-grouped numbers consistently."""
    tokens = []
    for raw in re.findall(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?%?", str(text or "")):
        token = raw.replace(",", "")
        try:
            number = float(token.rstrip("%"))
            normalized = str(int(number)) if number.is_integer() else str(number)
            tokens.append(normalized + ("%" if token.endswith("%") else ""))
        except ValueError:
            continue
    return tokens


def validate(slide, source):
    """Validate structure and flag numbers/quotes not supported by source text."""
    errors = []
    source = clean_text(source)
    title = clean_text(slide.get("title", ""))
    if not title:
        errors.append("Slide title is empty.")
    if len(title) > 110:
        errors.append("Title too long.")

    bullets = slide.get("bullets", [])
    if not isinstance(bullets, list):
        errors.append("Bullets must be a list.")
        bullets = []
    chart = slide.get("chart")
    if chart is not None:
        if not isinstance(chart, dict):
            errors.append("Chart must be a JSON object.")
        else:
            labels, values = chart.get("labels", []), chart.get("values", [])
            if not isinstance(labels, list) or not isinstance(values, list):
                errors.append("Chart labels and values must be lists.")
            elif len(labels) != len(values) or len(values) < 2:
                errors.append("Chart labels and values must match and contain at least two points.")
            else:
                try:
                    numbers = [float(value) for value in values]
                    if not all(math.isfinite(value) for value in numbers):
                        raise ValueError("Non-finite value")
                    source_numbers = set(_number_tokens(source))
                    for value in values:
                        token = _number_tokens(str(value))
                        if token and token[0] not in source_numbers:
                            errors.append(f"Unsupported chart value: {value}")
                except (TypeError, ValueError, OverflowError):
                    errors.append("Chart values must be finite numbers.")

    source_numbers = set(_number_tokens(source))
    slide_text = safe_json({k: slide.get(k) for k in ("title", "bullets", "body", "subtitle", "items", "kpis", "columns", "table", "timeline", "center_label")})
    for number in _number_tokens(slide_text):
        if number not in source_numbers:
            errors.append(f"Unsupported number on slide: {number}")
            break

    quotes = slide.get("source_quotes", [])
    if isinstance(quotes, list):
        for quote in quotes:
            quote = clean_text(quote)
            if quote and len(quote) >= 12 and quote.casefold() not in source.casefold():
                errors.append("Source quote is not an exact substring of the source.")
                break
    return errors[:8]


# ---------------------------------------------------------------------
# Global review
# ---------------------------------------------------------------------

async def review(slides, prompt):
    compact = [
        {
            "id": slide.get("id"),
            "title": slide.get("title"),
            "visual_type": slide.get("visual_type"),
            "first_bullet": (slide.get("bullets") or [""])[0],
        }
        for slide in slides
    ]
    try:
        response = await chat(
            "gemma",
            "Review presentation flow and repetition. Return JSON only.",
            f"""
Return JSON: {{"title_edits": {{}}, "order": []}}
Do not add facts. Keep every slide ID exactly as provided.
Keep edited titles concise and do not insert spaces inside words.

Prompt:
{prompt}

Slides:
{safe_json(compact)}
""",
            max_tokens=settings.review_max_tokens,
        )
        result = parse_llm_json(response)
        by_id = {slide.get("id"): slide for slide in slides}

        edits = result.get("title_edits", {})
        if isinstance(edits, dict):
            for slide_id, title in edits.items():
                if slide_id in by_id and isinstance(title, str):
                    by_id[slide_id]["title"] = clean_text(title)[:110]

        order = result.get("order")
        if isinstance(order, list):
            ordered, seen = [], set()
            for slide_id in order:
                if slide_id in by_id and slide_id not in seen:
                    ordered.append(by_id[slide_id])
                    seen.add(slide_id)
            ordered.extend(slide for slide in slides if slide.get("id") not in seen)
            if slides and ordered and ordered[0].get("id") != slides[0].get("id"):
                return slides
            return ordered
        return slides
    except Exception as exc:
        log.warning("Global review skipped: %s", exc)
        return slides
