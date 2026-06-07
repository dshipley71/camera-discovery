"""Shared neutral extraction boundary.

Concrete harvest/discovery services still own their budgets and outputs; shared
helpers in this package normalize evidence without assigning trust.
"""

from camera_discovery.evidence.media_records import ExtractedEvidence

__all__ = ["ExtractedEvidence"]
