"""Cache identity excludes caller identifiers, includes all generation inputs."""
import hashlib
import json
from app.config import settings

def content_key(request):
    data = {k: request.get(k) for k in ('prompt', 'text', 'options')}
    data['models'] = [settings.gemma_model, settings.glm_model]
    data['generation'] = {k: getattr(settings, k) for k in (
        'slides_min', 'slides_max', 'max_output_slides', 'default_slide_count',
        'planner_temperature', 'builder_temperature', 'planner_max_tokens',
        'builder_max_tokens', 'digest_max_tokens', 'parser_max_tokens',
        'review_max_tokens', 'chunk_tokens', 'min_contrast', 'enable_visual_qa')}
    return 'ppt-content:v3:' + hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
