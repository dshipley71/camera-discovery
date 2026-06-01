> **Source-alignment note:** This Codex implementation prompt must be copied into the repository under `docs/codex_prompt_media_playlists_rtsp_validation_dashboard.md` for traceability. The current source code is authoritative. If this prompt mentions a stale file, function, class, option, artifact name, or notebook name, inspect the repository and adapt to the verified current implementation instead of creating duplicate workflows.

# Codex Prompt — Media Playlist Exports, RTSP Support, Google-Dorked Public Source Discovery, and Media Validation Dashboard

You are working in the `camera-discovery` repository. Implement safe media playlist exports, source-policy-compliant RTSP support, guarded Google dorking for publicly available camera source discovery, and a cleaner top-level media validation dashboard summary. Follow the repository's root `AGENTS.md`, nested implementation notes, and current `/docs` conventions. Make the smallest coherent source, notebook, documentation, and test changes required.

This task is **not** a request to add Shodan-style camera scanning, default-credential testing, device fingerprinting, common-path probing, private IP camera enumeration, or search-engine hunting for exposed device/admin interfaces. RTSP support must be limited to URLs explicitly supplied by the user or extracted from public/allowed source pages/endpoints under the existing source-policy and block-policy rules. Google dorking in this task means constrained, operator-enhanced public web/source-page discovery for approved public camera directories, government/open-data pages, and other source-policy-compliant public pages only.

---

## Non-Negotiable Behavioral Rules

1. **Follow `AGENTS.md` and current implementation notes.**
   - No fake camera records, fake streams, fake validation results, fake coordinates, fake GeoJSON, fake browser success, or synthetic runtime inventories.
   - No hard-coded real-world locations, agencies, source domains, source-specific behavior, or one-off camera types.
   - Generic media normalization, generic URL canonicalization, playlist export, validation-status aggregation, and diagnostics are allowed.
   - Notebook-specific helper/display code belongs in notebooks, not `src/`.
   - Do not create `src/camera_discovery/notebook/`.

2. **Preserve the trust boundary.**
   - LLMs remain advisory only.
   - Deterministic code remains authoritative for bbox/geometry verification, coordinate acceptance, scope classification, media validation, trusted output authorization, artifact writing, and playlist export eligibility.
   - Playlist export must never promote candidates to trusted. It is only a convenience view over existing candidate/trust/validation state.

3. **Keep source-policy semantics intact.**
   - Blocked sources must remain globally blocked across blind search, directory rows, direct seed URLs, fetched pages/endpoints, extracted media URLs, harvest outputs, harvest handoff input, final candidates, and playlists.
   - Do not add Shodan, Censys, Zoomeye, FOFA, Insecam, or similar internet-asset search behavior.
   - Do not bypass `SOURCES.md` or block patterns for RTSP URLs.
   - Google dorking/search-operator logic must use the same source-policy and block-policy gates as ordinary blind search, directory rows, direct seeds, harvested records, extracted media, and playlists.
   - Operator-enhanced search results from new domains are source leads only until they pass existing source policy and target/scope/trust gates.

4. **Google dorking safety boundary.**
   - Google dorking means query refinement with public search operators such as `site:`, quoted phrases, `filetype:`, `intitle:`, `inurl:`, `OR`, and exclusion terms.
   - Use operator-enhanced queries only to find public camera listing pages, public livestream pages, public government/open-data pages, public JSON/API documentation pages, and other source-policy-compliant public camera directories.
   - Every generated query must include at least one normalized target/location term and at least one camera-type/public-camera term unless the current source already has stricter query contracts.
   - Prefer `site:`-restricted dorks for domains already allowed in `SOURCES.md`. For unknown domains, results must be treated as candidate source leads, not trusted media.
   - Do **not** generate dorks intended to find exposed device UIs, admin panels, default login pages, credentials, config files, backups, directory listings with secrets, private networks, or vulnerable camera endpoints.
   - Do **not** use vendor/device-fingerprint dorks, default path dorks, port/protocol hunting dorks, credential-bearing dorks, `rtsp://` hunting dorks, or queries copied from exploit databases.
   - Do **not** search blocked internet-asset indexes or use Google as a proxy to reach blocked sources.
   - Do **not** add discovered media directly to trusted outputs. Operator-enhanced discovery only expands source/page discovery; normal extraction, validation, scope, and trust rules still apply.

5. **RTSP safety boundary.**
   - Do **not** generate RTSP URLs from IP addresses, domains, vendor names, paths, or guessed camera endpoints.
   - Do **not** test default credentials.
   - Do **not** probe common RTSP paths such as `/live`, `/Streaming/Channels/101`, `/cam/realmonitor`, etc. unless that exact URL was explicitly provided by the user or extracted verbatim from an allowed public source page/endpoint.
   - Do **not** brute-force ports, paths, usernames, passwords, camera vendors, or schemes.
   - Do **not** treat an unauthenticated RTSP URL as trusted unless the normal target scope, coordinate, validation, and trust gates authorize it.
   - Reject or quarantine private/reserved/local network URLs where the repository already has a URL safety helper. If no helper exists, add a generic helper for RFC1918, loopback, link-local, multicast, and localhost-style hosts, and apply it consistently to media validation/export without breaking legitimate public URLs.

6. **Keep architecture boundaries.**
   - CLI commands remain thin.
   - Workflow orchestration stays in `runners/` and service/facade classes.
   - Shared media classification/canonicalization belongs in `extraction/` or an existing shared helper module.
   - Harvest-specific output helpers stay under `harvest/` or existing harvest services.
   - Review/validation output writing stays in the review/validation pipeline or an appropriate output helper.

7. **Preserve public compatibility unless explicitly changed.**
   - Existing CLI options, public imports, environment variables, artifact names, schemas, and test contracts must continue working.
   - Do not rename `camera.geojson` to `cameras.geojson` as part of this task unless the current repository already has an agreed migration path.
   - Do not add validation caps, sampling defaults, or truncation behavior.

8. **Do not weaken tests.**
   - Add tests for the requested behavior.
   - Do not relax existing assertions to hide regressions.
   - Do not use brittle tests that depend only on line counts or formatting.

---

## First Step: Inspect Current Source Before Editing

Before changing anything, inspect the actual repository and identify current implementations of:

- `AGENTS.md` rules and any nested implementation notes;
- `RunConfig`, `HarvestConfig`, `CameraCandidate`, `HarvestedUrlRecord`, `ValidationSummary`, and `OutputSummary`;
- media URL classification/canonicalization helpers;
- harvest media filtering and `SUPPORTED_MEDIA_TYPES`;
- harvest artifact writers for `camera_urls.txt`, typed URL files, JSONL files, handoff manifests, and summaries;
- normal pipeline validation in `ReviewAndValidationPipeline`;
- current HLS/image snapshot validation status strings and status categorization;
- source-policy/block-policy checks for discovered/fetched/extracted media URLs;
- SearchAgent/blind-search query construction, existing search-provider abstractions, source-lead handling, and any blocked-source filtering before/after search;
- existing query-template logic for location terms, camera-type intent terms, exclusions, and search-result provenance;
- final output writers for GeoJSON, inventory JSONL, candidate CSV, map, review ZIP, `RUN_EXPLANATION.md`, and run-explanation JSON;
- notebook files under `notebooks/` and notebook tests;
- docs in `README.md`, `docs/runtime_configuration.md`, `docs/output_artifacts.md`, `docs/README.md`, `notebooks/README.md`, and other source-aligned markdown files.

If part of this functionality already exists, preserve it and fill only the verified gaps.

---

## Required Functional Change 1 — Add M3U/TXT Playlist Exports

Add safe, deterministic playlist exports to normal pipeline output and harvest output where appropriate.

### Normal `camera-discovery run` outputs

After candidate validation/output classification, write playlist/text artifacts under a clear output location. Prefer a subdirectory to avoid clutter, for example:

```text
playlists/
  trusted_media.m3u
  trusted_media.txt
  untrusted_review_media.m3u
  untrusted_review_media.txt
  hls_candidates.m3u
  hls_candidates.txt
  rtsp_candidates.m3u
  rtsp_candidates.txt
  live_or_reachable_media.m3u
  live_or_reachable_media.txt
  dead_or_restricted_media.txt
  image_snapshots.txt
```

Adjust names only if the current repository has an existing artifact naming convention. Keep names stable once chosen and document them.

### Playlist eligibility rules

- `trusted_media.*` contains only candidates that are also eligible for trusted output under the existing trust rules.
- `untrusted_review_media.*` contains review candidates that are not trusted but are retained for audit/review.
- `hls_candidates.*` contains candidates whose media type is HLS or whose URL is clearly `.m3u8`.
- `rtsp_candidates.*` contains RTSP/RSTS candidates only when such URLs were explicitly supplied or extracted from allowed public sources.
- `live_or_reachable_media.*` contains candidates whose validation status indicates a reachable/live media endpoint, such as existing active HLS/image snapshot statuses and new RTSP reachable statuses.
- `dead_or_restricted_media.txt` contains media URLs with validation statuses such as dead/offline/restricted/auth-required/private-network/not-validatable. This file is for diagnostics only; do not write a `.m3u` for dead/restricted media.
- `image_snapshots.txt` contains image snapshot URLs. Do not pretend images are playable videos in M3U unless there is an existing user-facing reason to do so.

### M3U format

Use standard extended M3U:

```text
#EXTM3U
#EXTINF:-1 tvg-name="Camera Name" group-title="trusted",Camera Name
https://example.org/live/camera.m3u8
```

Requirements:

- Use stable, human-readable titles from existing candidate fields where available.
- Escape or sanitize M3U metadata safely.
- Do not drop query strings or tokens from playable URLs unless the existing URL canonicalizer already does so for dedupe. If URLs include credentials/userinfo, avoid echoing credentials in descriptive metadata, summaries, or logs beyond the URL artifact itself when required for playback.
- Preserve exact playable media URLs in playlist entries.
- Deduplicate by canonical media URL plus target id where relevant.
- Do not include blocked-source URLs.
- Do not include candidates rejected by private-network/local-host safety checks.

### TXT format

TXT files should be one URL per line, with no extra prose. This keeps them usable by VLC, scripts, notebooks, and manual review.

### Summaries

Add a machine-readable playlist status artifact, for example:

```text
logs/playlist_export_summary.json
```

Expected fields:

```json
{
  "created": true,
  "output_dir": "playlists",
  "files": {
    "trusted_media_m3u": "playlists/trusted_media.m3u",
    "trusted_media_txt": "playlists/trusted_media.txt"
  },
  "counts": {
    "trusted_media": 12,
    "untrusted_review_media": 88,
    "hls_candidates": 77,
    "rtsp_candidates": 4,
    "live_or_reachable_media": 53,
    "dead_or_restricted_media": 20,
    "image_snapshots": 31
  }
}
```

Also add playlist outputs to:

- `logs/output_summary.json` or `OutputSummary` if that is the current output contract;
- `logs/run_explanation.json`;
- `RUN_EXPLANATION.md`;
- `review_artifacts.zip`.

### Harvest outputs

For `camera-discovery harvest-urls`, add playlist/TXT exports when the harvest contains playable media records:

```text
playlists/
  harvested_media.m3u
  harvested_media.txt
  harvested_hls.m3u
  harvested_hls.txt
  harvested_rtsp.m3u
  harvested_rtsp.txt
  harvested_image_snapshots.txt
logs/playlist_export_summary.json
```

Harvest remains extraction-only. Do not validate, geocode, scope, trust, or write GeoJSON/maps during harvest.

---

## Required Functional Change 2 — Add RTSP Support

Add RTSP support across media classification, harvest filtering, candidate metadata, validation, outputs, documentation, and tests. This support must be generic and safe.

### Media classification and filtering

Update existing shared media classification helpers to recognize:

```text
rtsp://...
rtsps://...
```

Use a normalized media type such as:

```text
rtsp
```

Add `rtsp` to harvest media filters. The following should work where media filters are accepted:

```bash
--media rtsp
--media rtsp,hls
--media stream
```

If the current filter system has media categories such as `stream`, define whether RTSP belongs to `stream` and document that behavior.

### Extraction

Update generic media extraction patterns so RTSP URLs embedded in public source pages, JSON, JavaScript state, or structured records can be extracted when they appear verbatim.

Requirements:

- Extract only full RTSP/RSTS URLs that appear in collected source content.
- Do not synthesize, guess, expand, or mutate RTSP URLs beyond existing URL decoding/canonicalization cleanup.
- Preserve URL query strings and path exactly enough for playback.
- Respect source-policy block rules.
- Apply private/reserved/local network safety rules before validation/export.

### Candidate metadata

For RTSP candidates, set or preserve:

```json
{
  "media_type": "rtsp",
  "asset_role": "rtsp_stream" // only if an asset-role field exists and this fits current conventions
}
```

Do not disturb existing HLS/image snapshot metadata.

### Validation

Add RTSP validation that is safe, bounded, and optional within existing validation profiles.

Recommended behavior:

- RTSP validation runs only for candidates selected by the existing validation pipeline.
- It must never enumerate paths or credentials.
- It should validate only the exact RTSP/RSTS URL already present on the candidate.
- Use `ffprobe` via `subprocess.run` if no existing media-probe helper exists.
- Bound runtime with a short timeout derived from `RunConfig.http_timeout` or a narrower safe cap.
- If `ffprobe` is unavailable, return a clear status such as `rtsp_validation_unavailable` and keep the candidate untrusted/review-only.
- If the RTSP endpoint requires authentication or refuses access, return `restricted_rtsp` or `auth_required_rtsp`.
- If the endpoint times out or cannot connect, return `dead_rtsp` or `offline_rtsp`.
- If media stream metadata is readable, return `active_rtsp_verified`.
- Do not log secrets. If ffprobe stderr/stdout is captured for diagnostics, redact credentials/userinfo and keep logs bounded.

Update validation status categorization so:

- `active_rtsp_verified` counts as live/reachable;
- `restricted_rtsp` / `auth_required_rtsp` count as restricted in the new dashboard;
- `dead_rtsp` / `offline_rtsp` count as dead;
- `rtsp_validation_unavailable` counts as unknown or not validated, not trusted.

### Browser/map UI

Browsers generally cannot play RTSP directly. Do not add fake RTSP playback to `map.html`.

Expected UI behavior:

- Show RTSP candidates in table/GeoJSON/map when they have coordinates and pass normal output rules.
- The popup/button can label RTSP as “Open RTSP URL” or “Copy/Open in external player” rather than trying to play it with hls.js.
- HLS playback behavior must remain unchanged.
- Image snapshot refresh behavior must remain unchanged.

---

## Required Functional Change 3 — Add Guarded Google Dorking for Publicly Available Camera Source Discovery

Add optional, source-policy-compliant Google dorking/query-operator support to the existing blind search/SearchAgent path. This is a query-construction enhancement, not a new internet-device scanner.

### Intended behavior

When enabled by configuration or an existing discovery profile, the SearchAgent may generate a small, bounded set of operator-enhanced search queries that help find public camera source pages and public camera metadata pages. These queries should supplement—not replace—the current normal search queries.

Recommended operator families:

```text
site:{allowed_source_domain} {target_terms} {camera_type_terms}
site:{allowed_source_domain} {target_terms} ({public_camera_terms})
site:{allowed_source_domain} filetype:json {target_terms} {camera_type_terms}
site:{allowed_source_domain} filetype:geojson {target_terms} {camera_type_terms}
site:{allowed_source_domain} intitle:{public_camera_title_terms} {target_terms}
site:{allowed_source_domain} inurl:{generic_public_camera_page_term} {target_terms}
```

Use actual repository query-builder syntax and escaping conventions. Do not paste these examples blindly if the current implementation expects a different search-provider format.

### Query construction requirements

- Build dorks from normalized target intent and camera-type intent already produced by the pipeline.
- Every generated dork must contain at least one target/location term and at least one public-camera/camera-type term.
- Prefer dorks scoped to already allowed `SOURCES.md` domains via `site:`.
- If the existing SearchAgent supports candidate source discovery from unknown domains, allow non-`site:` dorks only as source leads and only under the same policy path as other blind-search results.
- Keep the number of dork queries bounded by existing search-query/candidate limits. Do not add unbounded Google query expansion.
- Deduplicate normal and dorked query results by canonical URL.
- Preserve search-result provenance, for example `discovery_query_kind="google_dork"` or equivalent, so notebook/docs/run explanations can show where candidates came from.
- Add operator-specific exclusions for known blocked domains and blocked source families when the search provider supports negative terms, but do not rely on search-provider exclusions as the only block. Always reapply deterministic block-policy checks after results return.

### Allowed dork intent

Operator-enhanced queries may target:

- public camera directory pages;
- public traffic/weather/beach/harbor/ski/wildlife/campus/etc. camera listing pages;
- public agency pages that intentionally publish camera feeds;
- public JSON, GeoJSON, ArcGIS, map-layer, or API metadata pages from source-policy-compliant sources;
- public livestream pages that do not require login, payment, private network access, or credential guessing.

### Forbidden dork intent

Do not generate, document, or test dorks intended to locate:

- exposed IP-camera device interfaces;
- admin/login pages;
- default credential opportunities;
- vendor/model fingerprints;
- common camera endpoint paths;
- private/reserved/local network hosts;
- open directory listings containing secrets, backups, configs, keys, passwords, or database dumps;
- `rtsp://` or `rtsps://` URLs directly through broad search;
- blocked internet-asset search engines, including Shodan, Censys, Zoomeye, FOFA, Insecam, or mirrors/results for them.

If an RTSP URL appears verbatim on an allowed public source page discovered through safe dorking, it may enter the RTSP support path described above. Do not search specifically for RTSP endpoints.

### Configuration

Use an existing configuration pattern if present. If a new setting is needed, prefer explicit and conservative names such as:

```text
CAMERA_DISCOVERY_ENABLE_GOOGLE_DORKING=false
CAMERA_DISCOVERY_MAX_DORK_QUERIES=8
```

If the current repository has profile-based search-query knobs instead of feature flags, wire dorking into that existing structure. Default should be disabled or conservative unless existing docs indicate blind-search query expansion is expected by default.

### Outputs and explanations

Include dorking status in run explanation artifacts when used:

```json
{
  "google_dorking": {
    "enabled": true,
    "queries_generated": 6,
    "results_seen": 42,
    "results_after_block_policy": 18,
    "promoted_source_leads": 5,
    "candidates_extracted": 12
  }
}
```

Use actual field names consistent with current `run_explanation.json` conventions. Do not include full query text in user-facing summaries if it contains sensitive-looking tokens or URLs; it is acceptable to include sanitized query families/counts.

### Notebooks

Notebook updates should show whether Google dorking was enabled and list high-level counts from run explanations when present. Do not make dorking the default for all notebook runs unless the repository already defaults to expanded blind search.

---

## Required Functional Change 4 — Add a Top-Level Media Validation Dashboard Summary

Add a concise machine-readable media validation dashboard summary with the required top-level keys:

```json
{
  "total_candidates": 1234,
  "validated": 800,
  "trusted": 120,
  "untrusted_review": 680,
  "dead": 300,
  "restricted": 40,
  "not_validated": 94
}
```

The concrete counts must come from the actual current run state; do not use placeholder numbers.

### Artifact location

Write the summary at the top level of the run output directory:

```text
media_validation_dashboard.json
```

Also copy or reference the same data in:

```text
logs/media_validation_dashboard.json
logs/run_explanation.json
RUN_EXPLANATION.md
review_artifacts.zip
```

If the repository has a single summary writer convention, use it, but keep `media_validation_dashboard.json` visible at the top level.

### Required semantics

Define counts deterministically in code and docs. Use these recommended semantics unless current source requires a more compatible equivalent:

- `total_candidates`: number of unique candidates after dedupe/merge and before final trusted/review artifact filtering.
- `validated`: number of candidates for which media validation was attempted in the current run.
- `trusted`: number of candidates written or eligible for trusted output under existing trust rules.
- `untrusted_review`: number of candidates retained for review output/table that are not trusted and not final-dead/rejected, if the current source distinguishes that; otherwise use the number written to untrusted review GeoJSON plus table-only review candidates and document the exact behavior.
- `dead`: number of candidates whose final validation status indicates dead/offline/invalid/static-dead media, excluding restricted/auth-required/private-network statuses where possible.
- `restricted`: number of candidates whose validation status indicates 401/403/auth-required/restricted/private-network/not-allowed access.
- `not_validated`: number of candidates not attempted by validation or marked with `not_validated` / `validation_disabled` / `rtsp_validation_unavailable` when no real media validation occurred.

Important: preserve existing `logs/validation_summary.json` compatibility. If existing `ValidationSummary.dead` historically includes restricted HTTP statuses, do not silently break old tests. The new dashboard may derive more precise `dead` and `restricted` counts from per-candidate validation statuses while leaving the legacy validation summary intact.

### Additional useful detail

The top-level keys above are required. You may add nested diagnostics if useful, for example:

```json
{
  "total_candidates": 1234,
  "validated": 800,
  "trusted": 120,
  "untrusted_review": 680,
  "dead": 300,
  "restricted": 40,
  "not_validated": 94,
  "by_media_type": {
    "hls": 700,
    "image_snapshot": 500,
    "rtsp": 34
  },
  "by_validation_status": {
    "active_live_unknown": 500,
    "restricted_http": 40,
    "dead_link": 200
  },
  "outputs": {
    "trusted_geojson_features": 120,
    "untrusted_geojson_features": 400,
    "candidate_table_rows": 900
  }
}
```

Do not allow the optional detail to obscure or rename the required top-level keys.

---

## Notebook Updates

Update notebooks as needed so users can see and inspect the new outputs without moving notebook logic into source.

At minimum, update relevant notebooks that run normal validation or harvest handoff workflows, especially:

```text
notebooks/camera_discovery_live_test.ipynb
notebooks/camera_discovery_pipeline_only_profiles_test.ipynb
notebooks/camera_discovery_harvest_hls_handoff_balanced_validation_test.ipynb
notebooks/camera_discovery_harvest_hls_handoff_full_validation_test.ipynb
notebooks/camera_discovery_harvest_all_media_handoff_full_validation_test.ipynb
notebooks/camera_discovery_harvest_urls_test.ipynb
```

Use the actual notebook set present in the repository. If a listed notebook is absent or renamed, update the corresponding current notebook instead.

Notebook requirements:

- Show or print `media_validation_dashboard.json` when present.
- List playlist artifacts when present.
- Preserve visible `!camera-discovery ...` CLI commands for long-running cells.
- Preserve `--http-timeout 10` usage in validation notebooks unless current docs/tests indicate a different value.
- Do not add validation caps.
- Do not move notebook helper code into `src/`.
- Do not import a notebook support package.
- Keep RTSP examples optional/commented unless adding them to a generic media-filter demo. Do not make RTSP the default notebook mode.
- Ensure notebooks remain valid JSON.

---

## Documentation Updates

Update markdown documentation to align with the implemented codebase.

Required docs to inspect and update as needed:

```text
README.md
docs/README.md
docs/runtime_configuration.md
docs/output_artifacts.md
notebooks/README.md
AGENTS.md
```

Only update `AGENTS.md` if needed to document the RTSP safety boundary or playlist/dashboard architecture rule. Do not turn `AGENTS.md` into user documentation.

Documentation must cover:

- New playlist/TXT artifacts and where they are written.
- New `media_validation_dashboard.json` summary and required fields.
- RTSP support scope and safety limits.
- RTSP media filter usage.
- RTSP validation behavior and dependency on `ffprobe` if implemented that way.
- Google dorking support scope: operator-enhanced public-source discovery only, configuration/profile behavior, provenance fields, and forbidden dork classes.
- Source-policy interaction for dorked search results, including blocked-domain enforcement before extraction/export.
- Browser/map limitation: RTSP is not played by hls.js/browser video; use external player/VLC-style tools.
- Harvest remains extraction-only.
- Normal run remains target-aware and trust-gated.
- Playlist artifacts are not trust artifacts by themselves.

Copy this prompt into:

```text
docs/codex_prompt_media_playlists_rtsp_validation_dashboard.md
```

If `docs/README.md` indexes historical prompts, add this prompt to the index.

---

## Test Requirements

Add focused tests that verify behavior without depending on real public cameras.

### Playlist export tests

Add or update tests to verify:

- Trusted candidates are written to `trusted_media.m3u` and `trusted_media.txt`.
- Untrusted review candidates are written to review playlist/TXT outputs without being promoted to trusted.
- HLS candidates appear in HLS playlist outputs.
- RTSP candidates appear in RTSP playlist outputs only when they are explicit candidates, not generated/probed.
- Image snapshot candidates appear in image snapshot TXT output and are not falsely treated as HLS.
- Blocked/private/rejected candidates are excluded or placed only in diagnostic TXT according to the implemented policy.
- `logs/playlist_export_summary.json` counts match the written files.
- `review_artifacts.zip` includes playlist artifacts.

### RTSP classification/extraction tests

Add tests to verify:

- `rtsp://public.example/live/stream` is classified as `rtsp`.
- `rtsps://public.example/live/stream` is classified as `rtsp` or a documented RTSP-secure variant.
- `--media rtsp` keeps RTSP records and excludes nonmatching media.
- `--media stream` includes RTSP if documented that way.
- RTSP extraction captures verbatim RTSP URLs embedded in JSON/HTML/JS content.
- No helper generates RTSP paths from a host or IP.
- Private/local RTSP URLs are rejected/quarantined according to the implemented safety helper.

### RTSP validation tests

Use monkeypatch/fakes around `subprocess.run` or the selected probe helper. Do not require live RTSP servers.

Verify statuses for:

- successful ffprobe-readable stream => `active_rtsp_verified`;
- ffprobe missing => `rtsp_validation_unavailable`;
- timeout/connect failure => `dead_rtsp` or `offline_rtsp`;
- auth/restricted output => `restricted_rtsp` or `auth_required_rtsp`;
- private/local URL => restricted/not-allowed status and no subprocess probe.

### Dashboard tests

Add tests to verify:

- `media_validation_dashboard.json` is written at the run output top level.
- `logs/media_validation_dashboard.json` is written or references identical content.
- Required top-level keys are present exactly:
  - `total_candidates`
  - `validated`
  - `trusted`
  - `untrusted_review`
  - `dead`
  - `restricted`
  - `not_validated`
- Counts are derived from actual candidate statuses, not placeholders.
- Restricted statuses are visible in `restricted` even if legacy `validation_summary.dead` remains backward compatible.
- Dashboard data is included in `RUN_EXPLANATION.md`, `logs/run_explanation.json`, and `review_artifacts.zip`.

### Google dorking query tests

Add tests around query construction and result handling. Do not call live Google/search engines in tests. Use fake search-provider responses.

Verify:

- dork query generation is disabled or conservative by default according to the chosen configuration behavior;
- generated dorks include at least one target/location term and one public-camera/camera-type term;
- `site:`-scoped dorks use allowed source domains when available;
- blocked domains are excluded in query construction when supported and always rejected after fake results return;
- forbidden fragments/classes are not generated, including device-admin/login, default-credential, vendor-fingerprint, common-path, private-network, and broad `rtsp://` hunting patterns;
- dorked results are tagged with provenance and are not promoted directly to trusted output;
- unknown-domain dorked results, if supported, enter the existing source-lead/review path rather than bypassing `SOURCES.md`;
- normal query generation still works when dorking is disabled.

### Notebook/docs tests

Update or add tests to verify:

- Notebooks are valid JSON.
- Notebooks do not import `camera_discovery_notebook` or any source notebook helper package.
- Validation notebooks do not add candidate caps.
- Relevant notebooks mention or inspect `media_validation_dashboard.json`.
- Relevant notebooks list `playlists/` output artifacts.
- Relevant notebooks show Google dorking status/counts when present.
- Docs mention RTSP safety limits, Google dorking guardrails, and playlist/dashboard artifacts.
- The new prompt file exists under `docs/`.

---

## Implementation Guidance

Use these as implementation hints, not rigid requirements. Adapt to the actual source.

### Shared playlist writer

Prefer a small helper such as:

```text
src/camera_discovery/utils/playlists.py
```

or an existing output/artifact module. The helper should be pure and easy to test:

- accept candidate/record rows;
- choose URL/title/group fields;
- dedupe;
- write M3U and TXT;
- return summary counts and paths.

Avoid burying playlist formatting in CLI or notebooks.

### Media type helpers

If media classification is split between normal discovery and harvest, consolidate only enough to prevent inconsistent HLS/image/RTSP behavior. Do not perform a broad refactor unless necessary.

### Validation dashboard helper

Prefer a helper that derives dashboard metrics from current run objects and per-candidate statuses. This keeps `ReviewAndValidationPipeline._write_outputs` readable.

Possible shape:

```python
def build_media_validation_dashboard(candidates, trusted_rows, review_rows, validation_summary, output_summary) -> dict[str, Any]:
    ...
```

### RTSP URL redaction

When writing diagnostic messages, summaries, or probe stderr, redact credentials/userinfo:

```text
rtsp://user:password@example.org/live
→ rtsp://***:***@example.org/live
```

Do not mutate the actual playable URL in playlist/TXT artifacts unless repository policy requires redaction everywhere.

---

## Acceptance Criteria

This task is complete when:

1. Normal runs write playlist/TXT artifacts and a playlist summary.
2. Harvest runs write playlist/TXT artifacts for harvested media records where appropriate.
3. Normal runs write top-level `media_validation_dashboard.json` with the required keys and real counts.
4. Optional Google dorking/query-operator support is added only as guarded public-source discovery, with source-policy enforcement, provenance, bounded query expansion, and forbidden dork classes blocked by tests.
5. `logs/run_explanation.json`, `RUN_EXPLANATION.md`, and `review_artifacts.zip` include or reference dashboard, playlist, and dorking-status outputs when present.
6. RTSP URLs are classified, filtered, carried through candidate metadata, validated safely, and exported without any URL generation/probing/credential testing.
7. HLS and image snapshot behavior remains unchanged except for new summaries/playlists.
8. RTSP is documented as external-player media, not browser/hls.js-playable media.
9. Existing tests continue to pass.
10. New tests cover playlist exports, RTSP classification/extraction/validation safety, Google dorking guardrails/provenance, dashboard summary, docs, and notebooks.
11. The prompt is copied into `docs/codex_prompt_media_playlists_rtsp_validation_dashboard.md`.

---

## Verification Commands

Run the most relevant checks before returning changes. For broad source changes, run:

```bash
python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q
python -m ruff check src tests
python -m mypy src/camera_discovery/core src/camera_discovery/llm
```

If notebook JSON was edited, run a lightweight notebook parse check, for example:

```bash
python - <<'PY'
import json
from pathlib import Path
for path in Path('notebooks').glob('*.ipynb'):
    json.loads(path.read_text(encoding='utf-8'))
    print('valid notebook json:', path)
PY
```

If `ffprobe` is not installed in the environment, RTSP tests should still pass through monkeypatch/fake subprocess behavior. Do not claim live RTSP validation succeeded unless it actually ran against a real reachable RTSP URL in an authorized environment.

---

## Final Response Expected from Codex

When finished, summarize:

- source files changed;
- notebook files changed;
- markdown files changed;
- new artifacts and schemas;
- RTSP safety guarantees added;
- Google dorking guardrails, configuration, and provenance added;
- tests added/updated;
- verification commands run and results;
- any checks that could not be run and why.
