# Passive Camera Intelligence

`camera-discovery` includes a passive intelligence layer that improves public camera search, candidate prioritization, validation handoff ordering, and review artifacts without changing the trust boundary.

Passive intelligence only analyzes evidence that the normal pipeline has already discovered from allowed public sources, configured directory sources, fetched pages, structured endpoints, browser-captured content, media URLs, or user-provided artifacts. It does **not** scan networks, brute-force RTSP paths, probe guessed vendor URLs, try credentials, capture packets, or perform vulnerability/CVE enrichment.

## What is scored

The pipeline scores both source rows and camera candidates on a deterministic 0-100 scale. Evidence bands are:

- `none`: 0
- `weak`: 1-24
- `moderate`: 25-49
- `strong`: 50-74
- `very_strong`: 75-100

Source-row signals include camera terms, structured endpoint hints, direct media/protocol evidence, safe passive signatures, source-policy status, configured directory/direct provenance, and passive HTTP metadata.

Candidate signals include direct HLS/RTSP/MJPEG/image snapshot evidence, structured camera metadata, source-provided coordinates, camera identity fields, inherited source evidence, safe signatures, target-scope status, validation status, and passive HTTP metadata.

Evidence score is used for prioritization and explanation only. It never bypasses target scope, source policy, validation, or trusted-output gates.

## Safe signature matching

The signature matcher recognizes generic camera/media path fragments and endpoint hints that are already present in discovered evidence. Examples include HLS playlists, snapshot paths, MJPEG paths, generic camera stream paths, ONVIF references, ArcGIS-style endpoint hints, and generic vendor hints.

Safe signatures may be matched against already-discovered URLs, titles, snippets, headers, structured fields, and metadata. They must not be used to generate URLs or probe hosts.

## HTTP metadata capture

When the existing discovery or validation flow already performs an HTTP request, the pipeline records a safe subset of HTTP metadata, including status, final URL, redirect count, content type, content length, server header, authentication presence, title, and response time.

Sensitive data is not stored. Cookies, authorization headers, API keys, tokens, credentials, and private headers are excluded or redacted.

## Protocol labels

Candidates receive passive protocol labels such as:

- `hls`
- `rtsp`
- `mjpeg`
- `image_snapshot`
- `dash`
- `webrtc`
- `rtmp`
- `srt`
- `mp4`
- `unknown_stream`
- `unknown`

Protocol labeling is based on already-discovered URLs, content types, playlist content, structured fields, and validation results. RTSP remains limited to exact RTSP URLs discovered from allowed public evidence.

## Artifacts

The passive intelligence layer writes or extends these artifacts:

- `logs/passive_intelligence_summary.json`
- `logs/source_row_evidence_summary.jsonl`
- `logs/candidate_evidence_summary.jsonl`
- `logs/candidate_priority_explanation.jsonl`
- `logs/candidate_priority_summary.json`
- `logs/run_explanation.json`
- `RUN_EXPLANATION.md`
- `media_validation_dashboard.json`
- `camera_candidates_table.csv`
- trusted/untrusted GeoJSON properties

The media validation dashboard includes a `passive_intelligence` section with evidence-band counts, protocol counts, signature-family counts, and top evidence reasons.

## Trust boundary

Passive evidence does not create trusted cameras. Trusted outputs still require the existing deterministic gates: allowed source policy, target scope, validation, coordinate requirements, and trust policy. Fast profile remains review-only.


## Change-control guardrails

Do not make assumptions or add unconfirmed behavior. Passive intelligence must remain limited to the requested evidence scoring, safe signature matching, HTTP metadata capture, protocol labeling, and explanation artifacts. New artifacts or fields should be added only when requested by the prompt or required by existing repository contracts. Target geometry artifacts and map overlays are outside passive discovery evidence and may be emitted only from explicit `primary_geometry_geojson`, `fallback_geometry_bbox`, or `last_fallback_geometry_bbox` fields.
