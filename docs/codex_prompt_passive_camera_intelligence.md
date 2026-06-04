# Codex Prompt: Integrate Passive Camera Intelligence for Search and Validation

## Objective

Update the `camera-discovery` repository to improve public camera search, candidate prioritization, media validation, and analyst review artifacts by adding **passive camera intelligence** only.

Implement the following highest-value improvements:

1. Evidence scoring for source rows and candidates.
2. Safe camera URL/path/vendor signature matching.
3. Better HTTP metadata capture.
4. Richer protocol labeling from already-discovered public evidence.
5. Better “why this candidate/source mattered” artifact summaries.

This work must improve search and validation prioritization without changing the core safety model of `camera-discovery`.

## Critical Behavioral Rules

Follow these rules exactly.

### Non-negotiable safety constraints

Do **not** add, port, enable, or normalize any of the following into normal `camera-discovery` behavior:

- Active network scanning.
- IP range scanning.
- Port scanning.
- RTSP brute forcing.
- Default path probing against arbitrary hosts.
- Credential probing.
- Default credential dictionaries.
- Login attempts.
- Packet capture.
- TShark/tcpdump behavior.
- Vulnerability scanning.
- CVE enrichment.
- Device exploitation.
- Shodan, Censys, Zoomeye, FOFA, insecam, or similar search-engine/security-index integrations.
- Any feature that turns camera-discovery into a security reconnaissance tool.

Passive intelligence means: **analyze evidence that camera-discovery has already discovered from allowed public web sources, configured directory sources, fetched pages, structured endpoints, media URLs, browser-captured content, or user-provided artifacts.**

Do not create new candidate URLs by guessing vendor paths.

Do not probe additional protocol endpoints unless the exact URL was already discovered from allowed public evidence.

### Existing project rules to preserve

- No stubs.
- No mock implementations.
- No fake outputs.
- No synthetic production data.
- No simulations presented as real behavior.
- No hard-coded real-world locations.
- No hard-coded agencies.
- No hard-coded source-specific behavior.
- No one-off domain hacks.
- No notebook-only source patching.
- Do not combine notebook code with source code.
- Keep the application location-agnostic.
- Respect `SOURCES.md` allowed and blocked source policy.
- Blind Search must still respect blocked sources.
- Trusted output rules must remain deterministic.
- Evidence score must never bypass target scope, source policy, validation, or trust rules.
- If validation is disabled, do not pretend validation occurred.
- If a candidate is untrusted, keep it untrusted.
- If an output is not validated, label it clearly as not validated.
- Do not make assumptions or add features, artifacts, fields, integrations, behaviors, sources, heuristics, or workflow changes that were not expected, requested, or confirmed by the user. When repository evidence is ambiguous, implement the narrowest change that satisfies the request and document any limitation instead of inventing behavior.
- Target geometry artifacts and map overlays must be emitted only from explicit resolver geometry hierarchy fields: `primary_geometry_geojson`, `fallback_geometry_bbox`, or `last_fallback_geometry_bbox`. Do not synthesize target geometry artifacts from `bbox`, `effective_bbox`, `nominatim_bbox`, `polygon`, geocoder point coordinates, LLM hints, or other convenience/legacy fields unless those values have first been stored in one of the explicit primary/fallback/last_fallback geometry fields by the resolver.

### Implementation posture

This is a minimal, production-quality source update. Do not rewrite the whole application.

Inspect the existing repository structure and place new code where it fits the current architecture. Prefer small cohesive modules over large invasive changes.

If an existing module already handles candidate extraction, source-row normalization, validation handoff, media classification, or run artifacts, integrate there rather than creating duplicate parallel pipelines.

## Conceptual Source

CamSniff may be used only as conceptual inspiration for passive camera-intelligence ideas such as:

- Camera-looking path fragments.
- Vendor/media URL patterns.
- Protocol labels.
- HTTP metadata usefulness.
- Multi-signal evidence scoring.

Do **not** copy or port CamSniff’s active scanning, probing, brute-force, credential, packet-capture, or vulnerability features.

If CamSniff code is available in the workspace, inspect it only to identify passive patterns. Re-implement safe concepts cleanly inside camera-discovery.

## Required Functional Changes

### 1. Add passive camera evidence scoring

Add evidence scoring for both source rows and candidate rows.

The score must be deterministic and explainable.

Recommended scoring range:

```text
0–100
```

Recommended output fields:

```json
{
  "camera_evidence_score": 0,
  "camera_evidence_band": "none|weak|moderate|strong|very_strong",
  "camera_evidence_reasons": [],
  "camera_evidence_signals": {}
}
```

Evidence scoring must be used for prioritization and artifact explanation only. It must not directly create trusted cameras.

#### Source-row evidence signals

Consider safe passive signals such as:

- Source URL appears to be a camera directory page.
- Source title/body contains camera/webcam/traffic/weather/live/snapshot/stream terms.
- Source content type is JSON, GeoJSON, ArcGIS-style JSON, JavaScript state, HTML, XML, playlist, or media.
- Source page contains multiple camera-like links.
- Source page contains structured camera rows.
- Source page contains route/direction/status/camera_id fields.
- Source page contains coordinates associated with camera-like records.
- Source host is allowed by `SOURCES.md`.
- Source host is not blocked by `SOURCES.md`.
- Source was promoted from repeated camera asset hosts.
- Source was discovered by browser capture and contains camera-like state.
- Source links to HLS, RTSP, MJPEG, image snapshot, DASH, WebRTC, RTMP, or similar media.

#### Candidate evidence signals

Consider safe passive signals such as:

- Candidate has direct HLS URL.
- Candidate has direct RTSP URL that was already discovered from allowed public content.
- Candidate has image snapshot URL.
- Candidate has MJPEG-like URL.
- Candidate came from structured camera metadata.
- Candidate has source-provided latitude/longitude.
- Candidate has camera_id, route, direction, status, agency label, or location text.
- Candidate URL path matches safe camera/media signature.
- Candidate source row has strong source evidence.
- Candidate passed target scope check.
- Candidate passed media validation.
- Candidate has live-looking media indicators.
- Candidate is not restricted, not dead, and not blocked.

The score must be decomposable into reasons. Avoid black-box scores.

### 2. Add safe URL/path/vendor/media signature matching

Create a safe signature module, for example:

```text
src/camera_discovery/passive_intelligence/signatures.py
```

or use the closest existing package structure.

The module should contain passive signatures for matching already-discovered evidence only.

Examples of safe signature categories:

```text
camera_path_fragment
snapshot_path_fragment
hls_path_fragment
rtsp_path_fragment
mjpeg_path_fragment
onvif_reference
vendor_hint
media_extension
playlist_extension
structured_endpoint_hint
```

Examples of safe generic path fragments:

```text
/axis-cgi/
/mjpg/
/mjpeg/
/snapshot
/snap.jpg
/image.jpg
/video
/stream
/live
/hls
/playlist.m3u8
/master.m3u8
/Streaming/Channels/
/ISAPI/
/onvif/
/cam/realmonitor
```

Rules:

- These signatures may only be matched against URLs, paths, headers, titles, snippets, and structured fields already discovered by camera-discovery.
- Do not use signatures to generate new URLs.
- Do not use signatures to probe hosts.
- Do not include credential-related signatures.
- Do not include default usernames or passwords.
- Do not include exploit paths.
- Do not include CVE-specific paths.
- Do not include source-domain-specific special cases.
- Keep signatures generic and location-agnostic.

Each match should produce structured output:

```json
{
  "signature_family": "camera_path_fragment",
  "signature_name": "axis_cgi_path",
  "matched_value": "/axis-cgi/",
  "confidence": "moderate",
  "reason": "URL path contains known camera media/control path fragment"
}
```

Do not log secrets or full sensitive query strings if present. Normalize or redact tokens where appropriate.

### 3. Improve HTTP metadata capture

Capture structured HTTP metadata for fetched source pages and candidate media where the existing fetch/validation flow already performs HTTP requests.

Recommended fields:

```json
{
  "http_status": 200,
  "final_url": "...",
  "redirect_count": 0,
  "content_type": "application/json",
  "content_length": 12345,
  "server": "nginx",
  "www_authenticate_present": false,
  "auth_realm": null,
  "title": "Traffic Cameras",
  "response_ms": 123,
  "fetch_error": null
}
```

Rules:

- Capture metadata only from requests camera-discovery already makes.
- Do not add new probing requests.
- Do not store cookies, authorization headers, API keys, tokens, or private headers.
- Use a strict header allowlist.
- Redact sensitive URL query parameters.
- Store metadata in source-row and candidate artifacts when available.
- Use metadata for evidence scoring and explanation.
- Do not treat a camera-looking `Server` header alone as sufficient evidence.

Suggested allowlisted headers:

```text
content-type
content-length
server
x-powered-by
www-authenticate
last-modified
etag
cache-control
access-control-allow-origin
```

If the repository already has an HTTP fetch abstraction, extend it there. Do not scatter ad hoc HTTP logic throughout the codebase.

### 4. Add richer protocol labeling

Add deterministic protocol/media labeling based on already-discovered URLs, content types, playlist content, structured fields, and validation results.

Recommended fields:

```json
{
  "protocol_label": "hls|rtsp|mjpeg|image_snapshot|dash|webrtc|rtmp|srt|mp4|unknown_stream|unknown",
  "media_family": "stream|image|video_file|playlist|page|structured_data|unknown",
  "protocol_confidence": "low|medium|high",
  "protocol_reasons": []
}
```

Protocol labeling must be passive.

Examples:

- `.m3u8` or HLS content type → `hls`
- `rtsp://` URL → `rtsp`
- MJPEG content type or multipart stream → `mjpeg`
- Refreshing image URL or static image endpoint with camera context → `image_snapshot`
- `.mpd` → `dash`
- WebRTC player config already present in page/JS → `webrtc`
- `rtmp://` discovered in public page/config → `rtmp`
- `.mp4` → `mp4`
- Unknown media-like URL → `unknown_stream`

Rules:

- Do not generate protocol endpoints.
- Do not probe RTSP paths.
- Do not infer a protocol from vendor name alone.
- Protocol labeling should support existing validation and playlist export behavior.
- RTSP support should remain limited to exact public RTSP URLs already discovered.

### 5. Add source and candidate explanation artifacts

Add or update run artifacts so analysts can understand why sources and candidates mattered.

Recommended artifacts:

```text
runs/<run-id>/logs/passive_intelligence_summary.json
runs/<run-id>/logs/source_row_evidence_summary.jsonl
runs/<run-id>/logs/candidate_evidence_summary.jsonl
runs/<run-id>/logs/candidate_priority_explanation.jsonl
```

If equivalent artifact paths already exist, extend them rather than creating duplicates.

Each source-row explanation should include:

```json
{
  "source_url": "...",
  "source_type": "search|directory|browser_capture|structured_endpoint|asset_host|manual",
  "source_allowed": true,
  "source_blocked": false,
  "http_metadata": {},
  "camera_evidence_score": 0,
  "camera_evidence_band": "weak",
  "camera_evidence_reasons": [],
  "signature_matches": [],
  "linked_candidate_count": 0,
  "why_it_mattered": "..."
}
```

Each candidate explanation should include:

```json
{
  "candidate_url": "...",
  "source_url": "...",
  "camera_type": "...",
  "protocol_label": "...",
  "media_family": "...",
  "http_metadata": {},
  "camera_evidence_score": 0,
  "camera_evidence_band": "strong",
  "camera_evidence_reasons": [],
  "signature_matches": [],
  "scope_status": "...",
  "validation_status": "...",
  "trust_level": "trusted|untrusted|not_validated",
  "why_it_mattered": "..."
}
```

The `why_it_mattered` field must be deterministic and generated from evidence reasons, not by an LLM unless the existing pipeline already has an LLM review stage for candidate interpretation. If an LLM is used, the deterministic evidence fields must remain primary.

Update `run_explanation.md` and `logs/run_explanation.json` to summarize passive intelligence results, including:

```json
{
  "sources_scored": 0,
  "candidates_scored": 0,
  "very_strong_candidates": 0,
  "strong_candidates": 0,
  "moderate_candidates": 0,
  "weak_candidates": 0,
  "top_evidence_signals": [],
  "protocol_label_counts": {},
  "signature_family_counts": {},
  "validation_prioritized_by_evidence": true
}
```

### 6. Integrate scoring into search and validation prioritization

Use evidence scores to prioritize, not to trust.

Allowed uses:

- Sort candidate validation queue.
- Promote high-evidence sources for deeper extraction.
- Prefer high-evidence structured endpoints during extraction.
- Rank untrusted review rows.
- Improve dashboard summaries.
- Explain why low-evidence rows were skipped or deprioritized.

Disallowed uses:

- Do not mark candidates trusted solely from evidence score.
- Do not bypass scope checks.
- Do not bypass media validation.
- Do not bypass `SOURCES.md`.
- Do not skip blocked-source checks.
- Do not create synthetic coordinates.
- Do not classify target scope from evidence score alone.
- Do not silently discard rows solely because score is low unless existing configured limits require prioritization. If limits require truncation, log the truncation reason.

### 7. Update exported candidate and GeoJSON properties

Where appropriate, add these fields to existing candidate JSONL, validation handoff, trusted GeoJSON, and untrusted GeoJSON outputs:

```text
camera_evidence_score
camera_evidence_band
camera_evidence_reasons
protocol_label
media_family
protocol_confidence
protocol_reasons
signature_matches
http_status
content_type
final_url
source_evidence_score
source_evidence_band
why_candidate_mattered
```

Rules:

- Keep GeoJSON properties compact.
- Avoid storing huge metadata blobs in GeoJSON.
- Full details should go into JSON/JSONL logs.
- Do not expose secrets or sensitive query parameters.
- Do not break existing artifact consumers.

### 8A. Enforce strict target geometry artifact emission

Any target geometry artifact, map target overlay, or review artifact entry representing target geometry must be emitted only from explicit resolver geometry hierarchy fields:

```text
primary_geometry_geojson
fallback_geometry_bbox
last_fallback_geometry_bbox
```

Rules:

- `primary_geometry_geojson` is the only primary polygon/multipolygon source for target geometry artifacts.
- `fallback_geometry_bbox` is the only fallback rectangle source for target geometry artifacts.
- `last_fallback_geometry_bbox` is the only last-fallback rectangle source for target geometry artifacts.
- Do not assume `target_geometry_geojson`, `polygon`, `bbox`, `effective_bbox`, or `nominatim_bbox` should produce a target geometry artifact unless the resolver also populated the corresponding explicit primary/fallback/last_fallback field.
- Do not emit geocoder point overlays as target geometry artifacts.
- If none of the explicit geometry fields is present, do not write `target_geometry.geojson` and log `created=false` with a clear skipped/no-explicit-geometry reason.
- Keep diagnostic resolver fields available in diagnostic JSON where already present, but do not treat them as artifact geometry sources.

### 8. Update media validation dashboard

Update the top-level media validation dashboard summary to include passive intelligence fields if the dashboard exists in this repository.

Add fields similar to:

```json
{
  "passive_intelligence": {
    "sources_scored": 0,
    "candidates_scored": 0,
    "candidate_evidence_bands": {
      "very_strong": 0,
      "strong": 0,
      "moderate": 0,
      "weak": 0,
      "none": 0
    },
    "protocol_label_counts": {},
    "signature_family_counts": {},
    "top_camera_evidence_reasons": []
  }
}
```

Do not remove existing required dashboard fields:

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

### 9. Documentation updates

Update relevant markdown documentation to describe the new passive intelligence behavior.

At minimum, update or add documentation covering:

- Passive intelligence overview.
- Evidence scoring.
- Safe signature matching.
- HTTP metadata capture.
- Protocol labeling.
- Artifact summaries.
- Safety exclusions.
- Difference between passive matching and active scanning.
- How evidence scores affect prioritization but not trust.
- How blocked sources remain enforced.
- How RTSP is handled only when exact RTSP URLs are discovered from allowed public evidence.

If there is a `docs/` directory containing Codex prompts, copy this prompt into:

```text
docs/codex_prompt_passive_camera_intelligence.md
```

or the nearest consistent prompt filename.

### 10. Notebook updates, if applicable

If notebooks are included and currently display run artifacts, update notebook cells only as needed to show the new passive intelligence summaries.

Rules:

- Do not move notebook helper modules into source code.
- Do not add notebook-specific package modules under `src/`.
- Do not patch source code from the notebook.
- Notebook should consume artifacts produced by source code.
- Keep runtime settings visible and clear.
- Do not silently change fast/balanced/full semantics.

Recommended notebook display additions:

- Passive intelligence summary.
- Candidate evidence band counts.
- Protocol label counts.
- Top evidence reasons.
- Link to detailed source/candidate evidence JSONL artifacts.

## Suggested Internal Design

Prefer a small module or package such as:

```text
src/camera_discovery/passive_intelligence/
  __init__.py
  signatures.py
  protocol_labels.py
  http_metadata.py
  evidence.py
  summaries.py
```

Use this only if it fits the repository. If the project already has better locations, use those.

### Suggested data structures

Use existing project style: Pydantic models, dataclasses, TypedDicts, or plain dicts depending on the codebase.

Recommended conceptual models:

```python
class HttpMetadata:
    http_status: int | None
    final_url: str | None
    redirect_count: int | None
    content_type: str | None
    content_length: int | None
    server: str | None
    www_authenticate_present: bool
    auth_realm: str | None
    title: str | None
    response_ms: int | None
    fetch_error: str | None
```

```python
class SignatureMatch:
    signature_family: str
    signature_name: str
    matched_value: str
    confidence: str
    reason: str
```

```python
class ProtocolLabel:
    protocol_label: str
    media_family: str
    protocol_confidence: str
    protocol_reasons: list[str]
```

```python
class CameraEvidence:
    camera_evidence_score: int
    camera_evidence_band: str
    camera_evidence_reasons: list[str]
    camera_evidence_signals: dict
    signature_matches: list[SignatureMatch]
```

### Evidence band thresholds

Use clear thresholds such as:

```text
0 = none
1–24 = weak
25–49 = moderate
50–74 = strong
75–100 = very_strong
```

If the repository already has a confidence system, align with it.

### Scoring principle

Make the score additive but capped at 100.

Example scoring guidance:

```text
+35 direct live media URL evidence
+30 structured camera record evidence
+20 source-provided coordinates
+15 camera_id / route / direction / status fields
+15 source page/title camera terms
+10 safe camera path signature
+10 protocol label high confidence
+10 allowed source confirmation
+10 validation successful
-20 restricted/auth-required
-20 dead media
-30 blocked source
```

Do not overfit these exact weights. Choose sensible weights, document them, and cover them with tests.

## Required Tests

Add tests for the passive intelligence layer and its integration.

Test coverage should include:

1. Safe signature matching:
   - Matches known camera/media path fragments in already-discovered URLs.
   - Does not generate new URLs.
   - Does not include credential/default-password logic.
   - Does not include exploit/CVE logic.

2. Protocol labeling:
   - `.m3u8` → HLS.
   - `rtsp://` → RTSP.
   - image extensions with camera context → image snapshot.
   - multipart MJPEG content type → MJPEG.
   - unknown media-like URL → unknown stream.

3. HTTP metadata:
   - Stores allowlisted headers only.
   - Redacts sensitive query parameters.
   - Does not store cookies or authorization headers.
   - Captures title/content type/status where available.

4. Evidence scoring:
   - Direct media + structured metadata gives high score.
   - Weak generic page gives low score.
   - Blocked source does not become trusted.
   - Restricted/dead media reduces evidence usefulness.
   - Score produces deterministic reasons.

5. Integration:
   - Validation handoff rows include evidence score and protocol label.
   - Untrusted GeoJSON rows include compact evidence fields.
   - Trusted GeoJSON rows still require normal validation/trust rules.
   - Evidence score changes prioritization order but does not bypass validation.
   - Dashboard includes passive intelligence summary.
   - Run explanation includes passive intelligence summary.

6. Safety regression tests:
   - No active scanning functions added.
   - No default credential strings added.
   - No RTSP brute-force path list used for probing.
   - No network expansion from signatures.
   - Blocked sources remain blocked.

Use the repository’s existing test framework. If tests require local fixtures, keep them small and deterministic. Do not introduce fake production outputs or mock pipeline behavior that hides missing implementation.

## Verification Commands

Inspect the repository and run the appropriate commands based on its actual configuration.

Likely commands may include:

```bash
python -m compileall src
python -m pytest
```

If the project has frontend or notebook-related checks, run the existing configured checks as well.

If the repository uses `ruff`, `mypy`, `npm`, `vitest`, or other tools, run only those that are already configured.

Do not invent a new toolchain unless required.

## Acceptance Criteria

The update is complete only when all of the following are true:

1. Source rows receive deterministic passive camera evidence scores.
2. Candidates receive deterministic passive camera evidence scores.
3. Safe signature matching exists and is used only on already-discovered evidence.
4. HTTP metadata is captured from existing fetch/validation requests.
5. Protocol labels are richer and explainable.
6. Search/deeper extraction/validation prioritization can use evidence score.
7. Evidence score does not bypass scope, validation, source policy, or trust rules.
8. Trusted/untrusted output behavior remains intact.
9. New artifacts explain why sources and candidates mattered.
10. Dashboard/run explanation summarize passive intelligence.
11. Documentation explains passive intelligence and its safety boundaries.
12. Tests cover scoring, signatures, metadata, protocol labels, artifacts, and safety regressions.
13. No active scanning, RTSP brute forcing, credential probing, packet capture, or vulnerability-oriented behavior is added.
14. No source-specific, agency-specific, or location-specific hardcoding is added.
15. Existing fast/balanced/full profile behavior is not silently changed.
16. No unrequested/unconfirmed features, artifacts, fields, integrations, or assumptions are added.
17. Target geometry artifacts and map overlays are emitted only from explicit `primary_geometry_geojson`, `fallback_geometry_bbox`, or `last_fallback_geometry_bbox` fields; no artifact geometry is synthesized from `bbox`, `effective_bbox`, `nominatim_bbox`, geocoder points, LLM hints, or other legacy/convenience fields.

## Final Response Required From Codex

When finished, provide a concise implementation summary including:

- Files changed.
- New modules added.
- How evidence scoring works.
- How safe signatures are constrained.
- How HTTP metadata is captured.
- How protocol labeling changed.
- Which artifacts were added or updated.
- Which tests were added.
- Which verification commands were run and their results.
- Any known limitations.

Do not claim success unless the relevant tests/checks were actually run.
