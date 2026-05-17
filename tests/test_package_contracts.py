from pathlib import Path


def test_production_llm_factory_requires_real_provider():
    factory = Path("src/camera_discovery/llm/factory.py").read_text(encoding="utf-8")
    assert "SUPPORTED_PROVIDERS" in factory
    assert "ollama" in factory
    assert "openai-compatible" in factory
    assert "bedrock" in factory
    assert "LLMConfigurationError" in factory


def test_readme_lists_required_provider_families():
    readme = Path("README.md").read_text(encoding="utf-8").casefold()
    assert "ollama" in readme
    assert "openai-compatible" in readme or "openai compatible" in readme
    assert "bedrock" in readme
