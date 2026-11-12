import importlib.util
from pathlib import Path
from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_env_example_is_valid(monkeypatch):
    for key in Settings.model_fields:
        monkeypatch.delenv(key.upper(), raising=False)
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=ROOT / '.env.example')
    assert settings.max_input_tokens == 100000
    assert settings.window_tokens == settings.chunk_tokens == 3000
    assert settings.planner_max_tokens == 5000
    assert settings.parser_max_tokens == 1200
    assert settings.digest_max_tokens == settings.builder_max_tokens == 2500
    assert settings.review_max_tokens == 1800
    assert settings.qa_max_tokens == 800


def test_env_repair_preserves_custom_values_and_credentials(tmp_path):
    spec = importlib.util.spec_from_file_location('fix_env', ROOT / 'scripts' / 'fix_env.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / '.env'
    original = ('DIGEST_MAX_TOKENS=change-me\nBUILDER_MAX_TOKENS=4500\n'
                'GEMMA_API_KEY=private-test-value\nSECRET_KEY=keep-this-value\n')
    path.write_text(original)
    assert module.repair(path) == ['DIGEST_MAX_TOKENS']
    fixed = path.read_text()
    assert 'DIGEST_MAX_TOKENS=2500' in fixed
    assert 'BUILDER_MAX_TOKENS=4500' in fixed
    assert 'GEMMA_API_KEY=private-test-value' in fixed
    assert 'SECRET_KEY=keep-this-value' in fixed
    assert next(tmp_path.glob('.env.before-token-fix-*')).read_text() == original
    assert module.repair(path) == []
