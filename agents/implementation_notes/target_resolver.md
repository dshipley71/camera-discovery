# TargetResolver Agent

Resolve target intent and geometry while preserving deterministic trust.

## LLM Advisory Duties

- Extract canonical target intent.
- Generate geocoder query variants.
- Rank/referee geocoder candidates semantically.

## Deterministic Duties

- Score bbox plausibility.
- Reject wrong-admin/wrong-country candidates.
- Reject address/POI for admin scopes.
- Reject tiny/oversized bboxes.
- Assign `bbox_verified` only after hard checks pass.

LLM geometry hints must be stored as unverified review hints only.
