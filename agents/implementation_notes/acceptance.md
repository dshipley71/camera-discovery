# Acceptance Criteria

The app passes when:

1. Target intent LLM runs as advisory extraction.
2. Geocoder referee LLM ranks candidates without overriding hard rejections.
3. Candidate review LLM labels candidates semantically without validating streams.
4. Geometry verification remains deterministic.
5. Stream validation remains deterministic/tool-based.
6. Trusted output authorization remains deterministic.
7. Final artifact writing is centralized in `ReviewAndValidationPipeline`.
8. Tests and notebook validation pass.
