# Acceptance and Verification

Use the smallest test set that proves the change, then run the full suite for broad source changes.

## Standard checks

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q
python -m ruff check src tests
python -m mypy src/camera_discovery/core src/camera_discovery/llm
```

GitHub Actions runs compile, Ruff, pytest, and a MyPy smoke check on pushes/PRs for Python 3.11 and 3.12.

## Contract checks

Run targeted contract tests when changing public interfaces:

```bash
PYTHONPATH=src python -m pytest -q \
  tests/test_package_contracts.py \
  tests/test_cli_contracts.py \
  tests/test_config_parameter_alignment.py
```

Public imports that must remain valid:

```python
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.harvest_engine import CameraUrlHarvestEngine
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline
from camera_discovery.services.target_resolver import TargetResolver
```

## Behavior-specific tests

| Area | Tests |
|---|---|
| Source policy | `tests/test_source_policy.py` |
| Blind-search parsing | `tests/test_blind_search_parsing.py` |
| Harvest media extraction | `tests/test_harvest_media_extraction.py` |
| Harvest structured records | `tests/test_harvest_structured_records.py` |
| Harvest handoff | `tests/test_harvest_handoff.py`, `tests/test_run_harvest_input.py` |
| Browser backend/preflight | `tests/test_browser_capture_expansion.py`, `tests/test_cloakbrowser_backend.py` |
| JSON endpoint metadata | `tests/test_json_endpoint_metadata_integration.py` |
| Candidate priority | `tests/test_candidate_priority.py` |
| Multi-target behavior | `tests/test_multi_target_contracts.py` |
| Output filtering/tables/maps | `tests/test_output_filtering.py`, `tests/test_coordinate_enrichment_and_tables.py`, `tests/test_geojson_viewer_contracts.py` |
| LLM/provider config | `tests/test_llm_provider_configuration.py` |
| Progress events | `tests/test_progress_events_contract.py`, `tests/test_cli_progress.py` |

## Notebook acceptance

Notebook updates should use real CLI commands against the package. Notebook-specific helper/display code belongs in the notebook. Do not move notebook-only helpers into `src/`.

Colab notebooks should retrieve `OLLAMA_API_KEY` from Colab userdata when available and set Ollama Cloud variables explicitly for reproducible runs.

## Trusted-output acceptance

Never create empty trusted files. Trusted artifacts require verified target geometry, in-scope coordinates, validation success, and `trust_policy=trusted_allowed`. Review artifacts must clearly remain untrusted.

## Artifact-size caution

`--write-intermediate-records` can write very large harvest files. It is appropriate for extraction debugging, not routine notebook use.
