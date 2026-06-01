# Codex Prompt 03 — Candidate Merge Semantics, Deprecation Docs, and Contract Tests

You are working in the `camera-discovery` repository after the process-hygiene and discovery-engine stage-split work. Clarify and test candidate merge semantics and related documentation without changing discovery behavior unless a verified bug is found.

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

## Baseline Verification Before Editing

Before changing files, inspect the current repository and record the relevant baseline in your final response:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q
```

If the full test suite is too slow or the environment lacks optional browser dependencies, run the targeted tests listed in this prompt and clearly report what was skipped and why. Do not fake optional dependency success.

---

## Problem

`CandidateSet.merge()` currently uses first-seen semantics for duplicates. That may be the intended behavior, but it is not clearly documented. For multi-target runs and harvest-input runs, developers need to understand exactly what key is used, which candidate wins, and whether the same stream under different targets is preserved or merged.

This prompt is about **documentation and contract tests first**. Only change merge behavior if the current source contradicts intended multi-target requirements.

---

## Required Inventory Before Editing

Inspect and report:

1. Location of `CandidateSet` and `CandidateSet.merge()`.
2. Current merge key semantics. Determine whether the key includes `target_id`, `stream_url`, normalized URL, media type, or other fields.
3. Existing tests for candidate merging, multi-target candidate preservation, dedupe, and harvest-input merging.
4. Whether duplicate streams across different targets are currently preserved or collapsed.
5. Whether first-seen behavior affects enrichment fields, coordinates, validation status, source metadata, or target metadata.

---

## Required Changes

### 1. Add an explicit docstring to `CandidateSet.merge()`

The docstring should explain:

- the merge/dedupe key;
- that the first-seen candidate is retained when the key collides;
- what happens to later duplicates;
- whether the same stream under different targets is preserved;
- why deterministic insertion order matters;
- that any future enrichment-priority behavior must be implemented as an explicit merge strategy, not as accidental ordering.

### 2. Add or update contract tests

Add tests for the actual current intended behavior. At minimum:

1. Same stream + same target duplicates keep the first candidate.
2. Same stream + different target IDs are preserved separately if that is the current/intended multi-target contract.
3. Merge order is deterministic.
4. Enrichment fields from a later duplicate do not silently override the first candidate unless current source intentionally merges metadata.

If the current implementation collapses same-stream/different-target candidates, compare this against the root `AGENTS.md` multi-location requirement. If it violates the requirement, fix it surgically and add a regression test.

### 3. Update docs

Update only relevant docs, for example:

- `docs/project_structure.md`;
- `docs/acceptance.md`;
- `agents/core_data_contracts_agent.md`;
- any data-contract or multi-target documentation.

The docs should make candidate dedupe/merge semantics clear enough that another coding agent can preserve them.

### 4. Avoid unrelated refactors

Do not refactor candidate models broadly. Do not change output schemas unless a verified merge-contract bug requires it.

---

## Suggested Targeted Tests

Run at least:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q \
  tests/test_multi_target_contracts.py \
  tests/test_package_contracts.py \
  tests/test_run_harvest_input.py \
  tests/test_target_and_extraction_regressions.py
PYTHONPATH=src python -m pytest -q
```

If Ruff exists, run it too.

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

