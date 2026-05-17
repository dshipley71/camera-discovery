# 08 — Tests Agent

Create tests that validate package configuration, deterministic verification boundaries, artifact contracts, and notebook validity without introducing production fallback providers.

## Test Policy

The production application always requires a real LLM provider. Tests must not add production code paths that bypass the provider requirement.

Use one of these approaches:

1. Static/unit tests that inspect configuration, provider selection, artifact schemas, and deterministic trust-gate behavior.
2. Optional integration tests that run only when real provider credentials are configured in the environment.
3. Notebook JSON validation.

## Required Test Areas

- LLM provider factory requires one of: Ollama/Ollama Cloud, OpenAI-compatible, Bedrock.
- Missing or unsupported provider fails fast with a clear configuration error.
- Stage-specific model overrides inherit the real provider connection settings.
- LLM target geometry is never treated as verified geometry.
- LLM geocoder referee scores cannot override deterministic hard rejections.
- LLM candidate semantic review cannot validate stream liveness or authorize trusted output.
- Fast mode writes review artifacts only.
- Balanced/Full modes can write trusted output only after deterministic gates pass.
- Notebook validates.

Run:

```bash
PYTHONPATH=src python -m compileall src
PYTHONPATH=src python -m pytest -q
```
