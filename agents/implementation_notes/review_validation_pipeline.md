# ReviewAndValidationPipeline Agent

Validate candidates and write outputs.

## Deterministic Duties

- Stream validation with HTTP/HLS checks.
- Trusted output authorization.
- Final artifact writing.

## Output Rules

- `camera.geojson` only when target geometry is verified and validation passes.
- `untrusted_camera_candidates.geojson` for review-only candidates.
- Never create empty trusted files.
- Package review artifacts consistently.
