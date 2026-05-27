# Codex Prompt 01 — Process Hygiene, CI, Linting, Config Cleanup

You are working in the `camera-discovery` repository after the structural refactor, blind-search repair, and harvest-handoff pipeline follow-up fixes. Implement process and hygiene improvements that reduce the chance of future refactor regressions without changing discovery behavior.

This prompt is intentionally limited to repository hygiene, CI, static checks, and small config cleanup. It must not change camera discovery semantics, harvest semantics, validation/trust rules, source behavior, browser capture behavior, or notebook runtime behavior except where explicitly requested below.

---

## Non-Negotiable Rules

1. **Follow the root `AGENTS.md`, nested implementation notes, and current `/docs` conventions.** The source code is authoritative. If this prompt mentions a stale file, function, class, option, artifact name, or module path, adapt to the verified current source instead of creating duplicate implementations.
2. **No fake runtime evidence.** Do not create fake camera records, fake streams, fake validation results, fake coordinates, fake GeoJSON, fake browser success, or synthetic runtime camera inventories.
3. **No source-specific hacks.** Do not hard-code real-world locations, agencies, source domains, source-specific behavior, or one-off camera types. Generic media normalization, generic URL canonicalization, generic candidate-priority scoring, and generic diagnostics are allowed when requested.
4. **LLMs remain advisory only.** Deterministic code/tools remain authoritative for bbox/geometry verification, coordinate acceptance, scope classification, media validation, trusted output authorization, and final artifact writing.
5. **Keep notebooks separate from source.** Notebook-specific helper code belongs in notebooks, not `src/`. Source modules must not import from notebooks.
6. **Make surgical changes.** Keep the refactored architecture intact: thin CLI commands, workflow orchestration in `runners/` and services, shared extraction helpers in `extraction/`, harvest-specific helpers in `harvest/`, and discovery helpers in `discovery/` / `enrichment/`. Do not collapse code back into god files.
7. **Do not weaken tests.** Add or update tests to protect behavior. Do not relax assertions to hide regressions. Avoid brittle line-count-only tests.
8. **Preserve public contracts unless explicitly changed.** Existing command names, existing options, public imports, environment variables, output artifact names, schema semantics, and global source block policy must continue to work.

---

## Baseline Verification Before Editing

Before changing files, inspect the current repository and record the relevant baseline in your final response:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q
```

If the full test suite is too slow or the environment lacks optional browser dependencies, run the targeted tests listed in this prompt and clearly report what was skipped and why. Do not fake optional dependency success.

---

## Problems to Address

1. No CI/CD workflow currently protects PRs and pushes.
2. No Ruff or MyPy configuration exists, despite the codebase using many typed models and dynamic records.
3. `core/config.py` defines helpers such as `_bool_env` and `_split_csv_env` after functions that call them. It works at runtime, but it violates least-surprise ordering.
4. `RunConfig.max_streams` is deprecated but still active. Explicit use should warn without breaking compatibility.
5. Recent regressions such as missing imports (`quote_plus`, `_dedupe_strings`, `_candidate_media_type`) would likely have been caught by a minimal linter.

---

## Required Changes

### 1. Add minimal GitHub Actions CI

Create `.github/workflows/tests.yml` or an equivalent workflow that runs on:

- pull requests;
- pushes to `main`;
- pushes to `dev` if the branch exists.

The workflow should:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m compileall -q src tests
python -m pytest -q
```

Use Python 3.11 and 3.12 if practical. Do not require Playwright browser downloads or CloakBrowser in the first workflow unless existing tests already mock/preflight those paths reliably. Optional browser dependencies should be tested only for import/preflight/missing-dependency behavior unless the repo already has stable CI support for real browser execution.

### 2. Add Ruff configuration

Add a practical `[tool.ruff]` and `[tool.ruff.lint]` section to `pyproject.toml`. Start with rules that catch real regressions at low cost:

- `E`, `F`, `I`, `UP`, `B` are good candidates.
- Avoid enabling strict style rules that create mass churn.
- It is acceptable to ignore `E501` if the repo uses long strings/CLI help text.

Add a CI step for Ruff if it passes without broad churn. If enabling Ruff reveals many pre-existing issues, either:

- fix only safe import/name/order issues directly related to this prompt, or
- configure Ruff narrowly enough that CI provides value now without a giant formatting-only change.

### 3. Add permissive MyPy configuration

Add a `[tool.mypy]` section to `pyproject.toml`. Start permissive enough to avoid a huge migration:

- `python_version = "3.11"`
- `warn_unused_ignores = true`
- `warn_redundant_casts = true`
- `no_implicit_optional = true`
- `ignore_missing_imports = true`

Do not make full-suite CI fail on strict MyPy unless the current code already passes. It is acceptable to add a non-blocking documented command or a targeted check for config/model modules.

### 4. Hoist config helpers

In `src/camera_discovery/core/config.py`, move `_bool_env`, `_split_csv_env`, and any comparable helper functions so they appear before `load_run_config()` / `load_harvest_config()` first call them.

This should be a mechanical reordering only. Do not change behavior.

### 5. Deprecation warning for explicit `max_streams` usage

`RunConfig.max_streams` is retained for compatibility, but explicit legacy configuration should warn. Implement the smallest safe behavior:

- If `CAMERA_DISCOVERY_MAX_STREAMS` is explicitly set in the environment, emit a `DeprecationWarning` explaining that it is superseded by `CAMERA_DISCOVERY_MAX_TOTAL_CANDIDATES` plus media-specific candidate caps.
- Do not emit noisy warnings every time a default `RunConfig` is created.
- Preserve the current alias/default behavior.
- Add a test that explicit `CAMERA_DISCOVERY_MAX_STREAMS` still works and emits a deprecation warning.

### 6. Update developer docs

Update only the docs needed for the new hygiene behavior:

- `README.md` or `docs/README.md` if they list developer commands;
- `docs/runtime_configuration.md` for the deprecated env var note if applicable;
- `docs/acceptance.md` if it lists verification commands.

Do not rewrite historical Codex prompts.

---

## Suggested Targeted Tests

Run at least:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q tests/test_config_parameter_alignment.py tests/test_package_contracts.py tests/test_cli_contracts.py
PYTHONPATH=src python -m pytest -q
python -m ruff check src tests
```

If MyPy is added as non-blocking, run and report:

```bash
python -m mypy src/camera_discovery/core src/camera_discovery/llm || true
```

Do not hide failures; either fix them or document why they are outside this prompt.

---

## Final Response Required from Codex

When finished, report:

1. Files changed.
2. What was verified before editing.
3. Summary of implementation decisions.
4. Public contracts preserved.
5. Tests/checks run and exact results.
6. Any limitations or follow-up work.
7. Confirmation that no fake/synthetic camera inventory, coordinates, validation results, GeoJSON, browser success, or source-specific hacks were introduced.

