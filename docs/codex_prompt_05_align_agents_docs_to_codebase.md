# Codex Prompt 05 — Align AGENTS.md, Agent Markdown, and Documentation to the Current Codebase

You are working in the `camera-discovery` repository after the process-hygiene, discovery-engine stage split, merge semantics, and candidate-priority changes. Align all Markdown documentation and coding-agent instructions to the current source code so another coding agent could regenerate or continue the codebase quickly and correctly.

This is a documentation-only task unless you find a clear doc/source contradiction that requires a separate source-code follow-up. Do not modify source code in this prompt unless explicitly instructed by the repository maintainer after reporting the contradiction.

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
9. **Do not assume or add unrequested behavior.** Do not infer, synthesize, or add helper workflows, notebook bootstrap behavior, artifact branches, compatibility behavior, fallback logic, source behavior, model behavior, or output artifacts that this prompt did not explicitly require or that is not confirmed by repository evidence. When in doubt, preserve existing behavior and document the uncertainty instead of adding unrequested behavior.

---

## Documentation Goal

The root `AGENTS.md`, files under `agents/`, implementation notes, and all active Markdown documentation should describe the current implemented codebase accurately. A coding agent reading these files should understand:

- the actual module layout;
- the current CLI commands/options;
- harvest versus normal pipeline responsibilities;
- handoff behavior;
- browser backend/preflight behavior;
- validation/trust rules;
- target/scope/geocoding authority rules;
- candidate-priority behavior;
- test and CI expectations;
- notebook conventions.

Historical `docs/codex_prompt_*.md` files are traceability artifacts. Do not rewrite them as if they are live docs. Add source-alignment notes only if needed and consistent with repo convention.

---

## Required Inventory Before Editing

Inspect the current source and docs. Record in the final response:

1. Current top-level package/module layout under `src/camera_discovery/`.
2. Current CLI commands and options for `run` and `harvest-urls`.
3. Current config/env variables for LLM providers, browser backend, harvest budgets, discovery budgets, and validation profiles.
4. Current harvest handoff schema/version and default handoff scope.
5. Current validation/trust rules and trusted/untrusted artifact behavior.
6. Current test/notebook files.
7. Markdown files updated.

---

## Markdown Files to Review

At minimum, review and update as needed:

```text
AGENTS.md
README.md
REPOSITORY_LAYOUT.md
camera-discovery-overview.md
docs/README.md
docs/project_structure.md
docs/runtime_configuration.md
docs/output_artifacts.md
docs/acceptance.md
docs/sources_blueprint.md
agents/*.md
agents/implementation_notes/*.md
```

Do not edit generated images. Do not rewrite old Codex prompt history unless adding a short note that historical prompts may mention old module locations.

---

## Required Documentation Updates

### 1. Architecture and module layout

Ensure docs reflect the current refactored structure:

- thin CLI commands;
- `runners/` workflow entry points;
- services for workflow coordination;
- `discovery/` stage helpers;
- `extraction/` shared extraction helpers;
- `harvest/` harvest-specific helpers;
- `enrichment/` deterministic/LLM-advisory enrichment helpers;
- browser backend/preflight modules;
- candidate-priority module if created by Prompt 04.

### 2. Behavioral rules

Ensure all agent docs preserve these rules:

- no fake/synthetic camera inventory;
- no hard-coded source-specific behavior;
- LLMs advisory only;
- deterministic code authoritative for geometry, scope, validation, trust, and final artifacts;
- notebook-specific helper code stays in notebooks.

### 3. Harvest mode and handoff

Document that harvest mode is extraction-only and bypasses target resolution, geocoding, validation, trust, scope, GeoJSON, maps, and review ZIP.

Document media-filter-aware handoff behavior:

- HLS-only handoff defaults to filtered HLS records;
- broader structured inventory is not injected by default into media-filtered handoff runs;
- normal `run --harvest-input` applies deterministic scope gating and existing validation/trust gates.

### 4. Candidate priority

If Prompt 04 has been implemented, document that coordinate-bearing, deterministically in-scope candidates are prioritized for validation budgets and review ordering, while coordinates alone do not make candidates trusted.

### 5. CLI and runtime configuration

Update docs for:

- `camera-discovery run --browser-backend`;
- `harvest-urls --browser-backend`;
- browser preflight behavior;
- recommended HLS harvest commands;
- profile differences (`fast`, `balanced`, `full`);
- Ollama Cloud / `OLLAMA_API_KEY` usage if documented in notebooks.

### 6. CI and developer workflow

If Prompt 01 has been implemented, document:

- `python -m compileall -q src tests`;
- `python -m pytest -q`;
- `python -m ruff check src tests`;
- any MyPy command that is supported.

---

## Acceptance Criteria

1. Markdown docs match the implemented source code.
2. No live doc suggests old module responsibilities that would rebuild god files.
3. Agent docs are actionable enough for a coding agent to resume work without guessing.
4. Historical Codex prompts remain traceable but not mistaken for active runtime docs.
5. No source code is modified.
6. Links/paths in docs are valid relative to the repo.

---

## Verification

Run documentation-safe checks:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q tests/test_package_contracts.py tests/test_cli_contracts.py
```

If markdown link checking tooling exists, run it. Otherwise, manually spot-check changed relative paths.

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

