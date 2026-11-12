"""Offline retrieval over visually annotated backgrounds."""
import csv
import json
import math
import re
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "PPT_Theme_Backgrounds_JPEGs"
STOP = set("a an and about as at be by create deck describe details for from in is it make of on or our presentation slide slides the this to use using with your".split())
ALIASES = {
    "terror": "terrorism", "terrorist": "terrorism", "terrorists": "terrorism",
    "airforce": "air force", "cybersecurity": "cyber security",
    "banking": "bank", "financial": "finance", "sustainable": "sustainability",
    "academic": "education", "universities": "university", "schools": "school",
    "ecosystems": "ecosystem", "oceans": "ocean", "satellites": "satellite",
    "signals": "signal", "attacks": "attack", "stocks": "stock",
}


def terms(text):
    words = re.findall(r"[^\W\d_]+", text.casefold())
    words = [word for token in words for word in ALIASES.get(token, token).split()
             if word not in STOP and len(word) > 1]
    return set(words) | {" ".join(pair) for pair in zip(words, words[1:])}


def normalize(vector):
    norm = math.sqrt(sum(value * value for value in vector.values()))
    return {word: value / norm for word, value in vector.items()} if norm else {}


def build_index():
    """Rebuild the bundled sparse vectors after editing the CSV."""
    with (ASSETS / "catalog.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    documents = [(terms(row["keywords"]), terms(row["description"])) for row in rows]
    vocabulary = set().union(*(category | caption for category, caption in documents))
    idf = {word: round(1 + math.log((len(rows) + 1) /
           (1 + sum(word in category or word in caption for category, caption in documents))), 6)
           for word in sorted(vocabulary)}
    for row, (category, caption) in zip(rows, documents):
        vector = normalize({word: idf[word] * (2 * (word in category) + (word in caption))
                            for word in sorted(category | caption)})
        row["vector"] = vector
    (ASSETS / "vectors.json").write_text(
        json.dumps({"idf": idf, "images": rows}, ensure_ascii=False), encoding="utf-8")


@lru_cache(maxsize=1)
def load_index():
    with (ASSETS / "vectors.json").open(encoding="utf-8") as source:
        return json.load(source)


def describe_request(request, pack, vocabulary):
    """Use the explicit brief plus the pipeline's existing source digest."""
    source = request.get("text") or {}
    prompt = request.get("prompt") or ""
    messages = source.get("messages") or []
    content = [source.get("content") or "", pack.get("source_text") or ""]
    content.extend(message.get("content") or "" for message in messages)
    digest = "\n".join(
        f'{topic.get("title", "")}: {topic.get("summary", "")}'
        for topic in pack.get("topics", []) if isinstance(topic, dict))
    passages = dict.fromkeys(
        passage.strip()
        for text in content
        for passage in re.split(r"(?<=[.!?])\s+|\n+", text)
        if passage.strip() and passage.strip() != prompt.strip())
    # Prefer passages with specific catalog concepts, retaining their original wording.
    ranked = sorted(passages, key=lambda passage: sum(
        vocabulary.get(word, 0.0) for word in terms(passage)), reverse=True)
    description = "\n".join([digest, *(passage[:1000] for passage in ranked[:12])])
    return prompt, description


def match_background(request, pack):
    index = load_index()
    brief, description = describe_request(request, pack, index["idf"])
    priority, context = terms(brief), terms(description)
    query = normalize({word: weight * (3 * (word in priority) + (word in context))
                       for word, weight in index["idf"].items()
                       if word in priority or word in context})
    best_image, best_score = None, 0.0
    for image in index["images"]:
        score = sum(value * query.get(word, 0.0) for word, value in image["vector"].items())
        if score > best_score:
            best_image, best_score = image, score
    if best_image:
        return {"image": best_image["image"], "category": best_image["category"],
                "score": round(best_score, 6)}
    return None


@lru_cache(maxsize=96)
def image_path(name):
    path = (ASSETS / name).resolve()
    return path if path.is_relative_to(ASSETS) and path.is_file() else None


@lru_cache(maxsize=32)
def backdrop(name, base_color, width, height):
    """Keep the existing theme colors readable over the matched image."""
    from io import BytesIO
    from PIL import Image, ImageOps

    path = image_path(name)
    if not path:
        return None
    size = (1600, round(1600 * height / width))
    with Image.open(path) as source:
        image = ImageOps.fit(source.convert("RGB"), size, Image.Resampling.LANCZOS)
    # Leave the image most visible on the right, where the catalog subjects sit.
    blend_mask = Image.linear_gradient("L").rotate(90, expand=True).resize(size)
    blend_mask = blend_mask.point(lambda value: round(12 + value * 0.20))
    output = BytesIO()
    Image.composite(image, Image.new("RGB", size, base_color), blend_mask).save(
        output, format="JPEG", quality=88)
    return output.getvalue()


if __name__ == "__main__":
    build_index()
