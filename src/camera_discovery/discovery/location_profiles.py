"""Discovery-facing location profile helpers.

Discovery imports this module when expanding safe public-source search queries.
Shared country/profile tables live in ``camera_discovery.geo.location_profiles``
so discovery and enrichment do not duplicate geography knowledge.
"""

from camera_discovery.geo.location_profiles import (
    LocationSearchProfile,
    country_aliases_for_location,
    country_code_from_location,
    localized_camera_terms_for_intent,
    location_search_profile,
    official_site_scopes_for_location,
    safe_exclusion_fragment,
)

__all__ = [
    "LocationSearchProfile",
    "country_aliases_for_location",
    "country_code_from_location",
    "localized_camera_terms_for_intent",
    "location_search_profile",
    "official_site_scopes_for_location",
    "safe_exclusion_fragment",
]
