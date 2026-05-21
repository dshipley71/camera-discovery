# 08 — Tests Agent

Tests should validate package configuration, deterministic trust boundaries, source policy, browser capture routing, JSON metadata extraction, output contracts, and notebook validity without adding production bypasses.

## Test policy

The production application requires real provider configuration for live LLM calls. Tests may use unit-level mocks/fakes only to exercise deterministic contracts. Do not add production code paths that silently bypass provider requirements.

Do not create fake camera inventories, fake streams, fabricated coordinates, synthetic validation success, or simulated runtime success as evidence of discovery quality.

## Required test areas

- provider factory supports Ollama/Ollama Cloud, OpenAI-compatible, and Bedrock;
- stage-specific provider/model overrides inherit common connection behavior;
- LLM target geometry is never trusted geometry;
- LLM location inference cannot supply coordinates;
- LLM geocoder referee cannot override deterministic hard rejections;
- LLM candidate semantic review cannot validate media or authorize trusted output;
- source registry allowed/blocked parsing and global blocked-pattern enforcement;
- `both` mode parallel row discovery and provenance preservation;
- browser capture backend selection, budgets, and diagnostics;
- JSON endpoint metadata extraction and preservation;
- image snapshots are treated as refreshing images, not videos;
- fast mode writes review artifacts only;
- balanced/full modes write trusted output only after deterministic gates pass;
- empty trusted files are not created;
- notebook JSON validates.

Run:

```bash
PYTHONPATH=src python -m compileall src
PYTHONPATH=src python -m pytest -q
```
