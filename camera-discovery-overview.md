# Camera Discovery Overview

`camera-discovery` discovers public camera media from user-specified target queries and produces either review/trusted pipeline artifacts or raw harvest artifacts.

## Workflows

### Normal pipeline: `camera-discovery run`

The normal pipeline is target-aware and performs:

1. runtime config loading;
2. target resolution and geocoder candidate scoring;
3. source-row discovery from blind search, `SOURCES.md`, or direct seeds;
4. generic media extraction from HTML, JSON/API/feed/layer endpoints, GeoJSON/ArcGIS records, and optional browser capture;
5. coordinate enrichment and deterministic scope classification;
6. candidate priority ordering;
7. optional validation depending on profile;
8. trusted/review artifact writing.

`fast` profile does not validate and blocks trusted output. `balanced` validates HLS playlists and image snapshots. `full` adds deeper HLS checks through the current full-profile validation path.

### Harvest workflow: `camera-discovery harvest-urls`

Harvest mode is extraction-only and intentionally bypasses:

```text
target resolution, geocoding, validation, trust, scope, LLM review, GeoJSON,
maps, cameras.md, and review ZIP generation
```

It is optimized for raw media collection and structured camera/media inventory generation. It can collect HLS, image snapshots, MJPEG, direct video files, generic stream-like URLs, and unknown media-like records depending on `--media`.

## Trust model

LLMs are advisory. They may help interpret target intent, rank geocoder candidates, infer place-name queries from candidate evidence, or review semantic relevance. They may not invent coordinates or authorize trusted output.

Trusted output requires deterministic evidence:

```text
verified target geometry + in-scope coordinates + successful media validation + trust_policy=trusted_allowed
```

Review artifacts are explicitly untrusted and may include unknown or out-of-scope candidates for audit.

## Harvest handoff

Harvest writes `harvest_handoff.json` with `schema_version: harvest-handoff/v2`. Media-filtered handoffs default to filtered media records. For example, an HLS-only harvest feeds HLS records into `run --harvest-input` by default rather than the broader structured image/media inventory.

Normal pipeline runs seeded by harvest input still perform target resolution, deterministic scope gating, validation, and trust checks. Harvest input never bypasses trust.

## Candidate priority

Coordinate-bearing, deterministically in-scope candidates are ordered ahead of unlocated candidates for validation budgets, tables, and review/map output. Coordinates alone do not make a candidate trusted, and out-of-scope coordinate-bearing candidates are not promoted above in-scope candidates.

## Browser capture

Static extraction runs first. Browser capture is optional, budgeted, and preflighted. Playwright is the default backend. CloakBrowser is selected with `--browser-backend cloakbrowser` or `CAMERA_DISCOVERY_BROWSER_BACKEND=cloakbrowser`.

If the backend is missing or unusable, diagnostics are written and repeated page-level failures should be avoided. Browser success must never be faked.


## Passive Intelligence

The application now includes passive camera intelligence to rank and explain source rows and candidates. It scores deterministic evidence, applies safe URL/path/media signatures to discovered content, captures redacted HTTP metadata from existing requests, and labels protocols such as HLS, RTSP, MJPEG, image snapshot, DASH, WebRTC, RTMP, SRT, and MP4. These signals improve prioritization and analyst review only; they do not bypass scope, validation, source policy, or trust gates.
