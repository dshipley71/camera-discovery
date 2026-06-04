"""Passive camera-intelligence helpers.

This package scores and labels evidence that the normal discovery pipeline has
already found. It must not scan, brute force, probe guessed paths, try
credentials, capture packets, or perform vulnerability enrichment.
"""

from camera_discovery.passive_intelligence.evidence import (
    add_passive_intelligence_to_dashboard,
    candidate_evidence_record,
    enrich_candidate_with_passive_intelligence,
    enrich_source_row_with_passive_intelligence,
    passive_intelligence_summary,
    source_row_evidence_record,
)
from camera_discovery.passive_intelligence.http_metadata import (
    http_metadata_from_response,
    redact_sensitive_url,
)
from camera_discovery.passive_intelligence.protocol_labels import classify_protocol
from camera_discovery.passive_intelligence.signatures import match_signatures

__all__ = [
    "add_passive_intelligence_to_dashboard",
    "candidate_evidence_record",
    "classify_protocol",
    "enrich_candidate_with_passive_intelligence",
    "enrich_source_row_with_passive_intelligence",
    "http_metadata_from_response",
    "match_signatures",
    "passive_intelligence_summary",
    "redact_sensitive_url",
    "source_row_evidence_record",
]
