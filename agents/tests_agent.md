# Tests Agent

Maintain tests that protect behavior and public contracts without depending on brittle file-size thresholds or incidental formatting.

## Standard checks

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q
python -m ruff check src tests
python -m mypy src/camera_discovery/core src/camera_discovery/llm
```

## Required coverage themes

- public import contracts;
- CLI option contracts for `run` and `harvest-urls`;
- source policy and blocked-source behavior;
- blind search parsing and diagnostics;
- harvest media filters, structured records, handoff behavior;
- harvest input into normal pipeline;
- deterministic target/scope behavior;
- candidate priority ordering;
- validation/trust output gates;
- progress event contract;
- browser preflight/missing-dependency behavior;
- provider configuration.

Do not fake browser success, validation success, camera records, coordinates, or GeoJSON. Optional dependencies should be tested with preflight/missing-dependency behavior unless stable real-browser CI support exists.


## Passive intelligence tests

Tests must cover safe signature matching, passive protocol labeling, HTTP metadata redaction/allowlisting, deterministic evidence scoring, validation/dashboard/artifact integration, and safety regressions proving no active scanning, URL generation from signatures, RTSP brute-force probing, credential probing, packet capture, or vulnerability enrichment was added.
