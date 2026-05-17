# Repository Layout

This combined repository keeps the runnable application source and the agent blueprint together.

```text
camera-discovery/
├── AGENTS.md                 # Root coding-agent instructions
├── agents/                   # Detailed agent build guides
├── docs/                     # Human-readable architecture and acceptance docs
├── notebooks/                # Google Colab / notebook workflow
├── src/camera_discovery/     # Application source
├── tests/                    # Contract/unit tests
├── SOURCES.md                # Runtime source registry
├── SOURCES.example.md        # Example source registry
├── pyproject.toml
├── README.md
└── Makefile
```

The implementation intentionally uses a streamlined three-stage pipeline:

```text
TargetResolver → CandidateDiscoveryEngine → ReviewAndValidationPipeline
```

LLMs are used as evidence interpreters/rankers for target intent, geocoder candidate ranking, and candidate semantic review. Deterministic/tool-based code remains responsible for geometry verification, stream validation, trusted-output authorization, and final artifact writing.
