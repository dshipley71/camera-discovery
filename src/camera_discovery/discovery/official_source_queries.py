"""Official public camera source-discovery query templates.

These templates target curated public-facing camera pages from government,
transportation, education, airport, park, port, and official tourism sources.
They do NOT target exposed device interfaces, admin pages, default credentials,
vendor fingerprints, or private-network hosts.

Each template group is keyed by a camera-intent slug that matches the
``camera_type_intent`` values emitted by the target-intent stage, plus a
shared ``default`` group used for any intent not covered by a specific group.

Usage::

    from camera_discovery.discovery.official_source_queries import (
        official_source_queries_for_intent,
    )

    queries = official_source_queries_for_intent("traffic", "Atlanta, Georgia")
"""

from __future__ import annotations

from camera_discovery.discovery.location_profiles import (
    localized_camera_terms_for_intent,
    official_site_scopes_for_location,
    safe_exclusion_fragment,
)

# ---------------------------------------------------------------------------
# Internal template registry
# ---------------------------------------------------------------------------

# Each entry is a (template, site_scope) pair.
# - template  : an f-string body where ``{loc}`` is replaced with the
#               caller-supplied location term.
# - site_scope: the site: restriction appended verbatim, or "" for no
#               restriction.  The caller may suppress it if needed.
#
# SAFETY NOTE: No template here may reference exposed device UIs, admin
# pages, default credentials, vendor fingerprints, common RTSP paths,
# private-network hosts, or blocked internet-asset search indexes.

_SAFE_EXCLUSIONS = safe_exclusion_fragment()

# --- General official public camera pages -----------------------------------
_GENERAL_GOV: list[tuple[str, str]] = [
    ('"public cameras" "{loc}"', "site:.gov"),
    ('"live cameras" "{loc}"', "site:.gov"),
    ('"camera map" "{loc}"', "site:.gov"),
    ('"webcam map" "{loc}"', "site:.gov"),
    ('"live webcam" "{loc}"', "site:.gov"),
    ('"webcams" "{loc}"', "site:.gov"),
    ('"camera feeds" "{loc}"', "site:.gov"),
    ('"public webcam" "{loc}"', "site:.gov"),
    ('"live camera" "{loc}" "official"', ""),
]

# --- Traffic / DOT / 511 cameras --------------------------------------------
_TRAFFIC_GOV: list[tuple[str, str]] = [
    ('"traffic cameras" "{loc}"', "site:.gov"),
    ('"live traffic cameras" "{loc}"', "site:.gov"),
    ('"road cameras" "{loc}"', "site:.gov"),
    ('"highway cameras" "{loc}"', "site:.gov"),
    ('"freeway cameras" "{loc}"', "site:.gov"),
    ('"511 cameras" "{loc}"', "site:.gov"),
    ('"511 traffic cameras" "{loc}"', "site:.gov"),
    ('"traveler information" "cameras" "{loc}"', "site:.gov"),
    ('"DOT cameras" "{loc}"', "site:.gov"),
    ('"department of transportation" "cameras" "{loc}"', "site:.gov"),
    ('"traffic camera map" "{loc}"', "site:.gov"),
    ('"road conditions" "cameras" "{loc}"', "site:.gov"),
    ('"winter road cameras" "{loc}"', "site:.gov"),
    ('"highway travel cameras" "{loc}"', "site:.gov"),
]

# --- Weather cameras --------------------------------------------------------
_WEATHER_GOV: list[tuple[str, str]] = [
    ('"weather cameras" "{loc}"', "site:.gov"),
    ('"weather camera" "{loc}"', "site:.gov"),
    ('"live weather camera" "{loc}"', "site:.gov"),
    ('"weather webcam" "{loc}"', "site:.gov"),
    ('"meteorological camera" "{loc}"', "site:.gov"),
    ('"airport weather camera" "{loc}"', "site:.gov"),
    ('"surface weather camera" "{loc}"', "site:.gov"),
    ('"road weather cameras" "{loc}"', "site:.gov"),
    ('"weather cameras" "{loc}"', "site:.edu"),
    ('"webcam" "weather" "{loc}"', "site:.edu"),
]

# --- Airport / aviation cameras ---------------------------------------------
_AIRPORT_GOV: list[tuple[str, str]] = [
    ('"airport cameras" "{loc}"', "site:.gov"),
    ('"airport weather camera" "{loc}"', "site:.gov"),
    ('"aviation weather camera" "{loc}"', "site:.gov"),
    ('"runway camera" "{loc}"', "site:.gov"),
    ('"airport webcam" "{loc}"', "site:.gov"),
    ('"terminal camera" "{loc}"', "site:.gov"),
    ('"airport live camera" "{loc}"', "site:.gov"),
    ('"airfield camera" "{loc}"', "site:.gov"),
    ('"aviation camera program" "{loc}"', "site:.gov"),
]

# --- Beach / surf / coastal cameras -----------------------------------------
_BEACH_GOV: list[tuple[str, str]] = [
    ('"beach cameras" "{loc}"', "site:.gov"),
    ('"beach webcam" "{loc}"', "site:.gov"),
    ('"surf camera" "{loc}"', "site:.gov"),
    ('"surf cam" "{loc}"', "site:.gov"),
    ('"coastal cameras" "{loc}"', "site:.gov"),
    ('"shoreline camera" "{loc}"', "site:.gov"),
    ('"pier camera" "{loc}"', "site:.gov"),
    ('"ocean camera" "{loc}"', "site:.gov"),
    ('"beach conditions" "camera" "{loc}"', "site:.gov"),
]

# --- Harbor / port / marina cameras -----------------------------------------
_HARBOR_GOV: list[tuple[str, str]] = [
    ('"harbor cameras" "{loc}"', "site:.gov"),
    ('"port cameras" "{loc}"', "site:.gov"),
    ('"marina cameras" "{loc}"', "site:.gov"),
    ('"harbor webcam" "{loc}"', "site:.gov"),
    ('"port webcam" "{loc}"', "site:.gov"),
    ('"marina webcam" "{loc}"', "site:.gov"),
    ('"ship channel camera" "{loc}"', "site:.gov"),
    ('"waterfront camera" "{loc}"', "site:.gov"),
    ('"ferry terminal camera" "{loc}"', "site:.gov"),
    ('"marine traffic camera" "{loc}"', "site:.gov"),
]

# --- Parks / public lands / wildlife cameras --------------------------------
_PARKS_GOV: list[tuple[str, str]] = [
    ('"park cameras" "{loc}"', "site:.gov"),
    ('"park webcam" "{loc}"', "site:.gov"),
    ('"live park camera" "{loc}"', "site:.gov"),
    ('"wildlife camera" "{loc}"', "site:.gov"),
    ('"wildlife webcam" "{loc}"', "site:.gov"),
    ('"trail camera" "{loc}"', "site:.gov"),
    ('"visitor center webcam" "{loc}"', "site:.gov"),
    ('"national park webcam" "{loc}"', "site:.gov"),
    ('"state park webcam" "{loc}"', "site:.gov"),
    ('"public lands camera" "{loc}"', "site:.gov"),
]

# --- Mountain / ski / snow cameras ------------------------------------------
_MOUNTAIN_GOV: list[tuple[str, str]] = [
    ('"mountain cameras" "{loc}"', "site:.gov"),
    ('"mountain webcam" "{loc}"', "site:.gov"),
    ('"snow camera" "{loc}"', "site:.gov"),
    ('"snow cameras" "{loc}"', "site:.gov"),
    ('"ski camera" "{loc}"', "site:.gov"),
    ('"ski webcam" "{loc}"', "site:.gov"),
    ('"pass camera" "{loc}"', "site:.gov"),
    ('"mountain pass camera" "{loc}"', "site:.gov"),
    ('"avalanche camera" "{loc}"', "site:.gov"),
]

# --- Campus / university cameras --------------------------------------------
_CAMPUS_EDU: list[tuple[str, str]] = [
    ('"campus webcam" "{loc}"', "site:.edu"),
    ('"campus cameras" "{loc}"', "site:.edu"),
    ('"live campus camera" "{loc}"', "site:.edu"),
    ('"university webcam" "{loc}"', "site:.edu"),
    ('"college webcam" "{loc}"', "site:.edu"),
    ('"campus live cam" "{loc}"', "site:.edu"),
    ('"weather camera" "{loc}"', "site:.edu"),
    ('"webcam" "campus" "{loc}"', "site:.edu"),
]

# --- City / civic / downtown cameras ----------------------------------------
_CITY_GOV: list[tuple[str, str]] = [
    ('"city webcam" "{loc}"', "site:.gov"),
    ('"downtown camera" "{loc}"', "site:.gov"),
    ('"downtown webcam" "{loc}"', "site:.gov"),
    ('"public square camera" "{loc}"', "site:.gov"),
    ('"city camera" "{loc}"', "site:.gov"),
    ('"municipal camera" "{loc}"', "site:.gov"),
    ('"public works camera" "{loc}"', "site:.gov"),
    ('"city live camera" "{loc}"', "site:.gov"),
]

# --- Construction / infrastructure project cameras -------------------------
_CONSTRUCTION_GOV: list[tuple[str, str]] = [
    ('"construction camera" "{loc}"', "site:.gov"),
    ('"construction cameras" "{loc}"', "site:.gov"),
    ('"project camera" "{loc}"', "site:.gov"),
    ('"project webcam" "{loc}"', "site:.gov"),
    ('"bridge construction camera" "{loc}"', "site:.gov"),
    ('"road project camera" "{loc}"', "site:.gov"),
    ('"capital project camera" "{loc}"', "site:.gov"),
    ('"infrastructure camera" "{loc}"', "site:.gov"),
]

# --- Public safety / emergency management cameras --------------------------
_SAFETY_GOV: list[tuple[str, str]] = [
    ('"emergency management" "camera" "{loc}"', "site:.gov"),
    ('"public safety camera" "{loc}"', "site:.gov"),
    ('"flood camera" "{loc}"', "site:.gov"),
    ('"river camera" "{loc}"', "site:.gov"),
    ('"dam camera" "{loc}"', "site:.gov"),
    ('"evacuation route camera" "{loc}"', "site:.gov"),
    ('"fire weather camera" "{loc}"', "site:.gov"),
    ('"disaster camera" "{loc}"', "site:.gov"),
]

# --- Official tourism / chamber / destination cameras ----------------------
_TOURISM: list[tuple[str, str]] = [
    ('"official visitor" "webcam" "{loc}"', ""),
    ('"official tourism" "webcam" "{loc}"', ""),
    ('"visitor bureau" "webcam" "{loc}"', ""),
    ('"tourism" "live camera" "{loc}"', ""),
    ('"chamber of commerce" "webcam" "{loc}"', ""),
    ('"destination webcam" "{loc}" "official"', ""),
    ('"live camera" "{loc}" "visitor center"', ""),
]


# ---------------------------------------------------------------------------
# Intent-to-template mapping
# ---------------------------------------------------------------------------

# Maps camera_type_intent keyword fragments → ordered list of template groups.
# Each group is a list of (template, site_scope) pairs.  Entries are listed
# from most-specific to least-specific; callers take the first N they need.
_INTENT_MAP: dict[str, list[list[tuple[str, str]]]] = {
    "traffic": [_TRAFFIC_GOV, _GENERAL_GOV, _CITY_GOV, _CONSTRUCTION_GOV, _SAFETY_GOV],
    "weather": [_WEATHER_GOV, _GENERAL_GOV, _MOUNTAIN_GOV, _AIRPORT_GOV, _CAMPUS_EDU],
    "airport": [_AIRPORT_GOV, _WEATHER_GOV, _GENERAL_GOV],
    "beach": [_BEACH_GOV, _HARBOR_GOV, _GENERAL_GOV, _TOURISM],
    "coastal": [_BEACH_GOV, _HARBOR_GOV, _GENERAL_GOV, _TOURISM],
    "harbor": [_HARBOR_GOV, _BEACH_GOV, _GENERAL_GOV],
    "port": [_HARBOR_GOV, _GENERAL_GOV],
    "marina": [_HARBOR_GOV, _BEACH_GOV, _GENERAL_GOV],
    "park": [_PARKS_GOV, _MOUNTAIN_GOV, _GENERAL_GOV, _TOURISM],
    "wildlife": [_PARKS_GOV, _GENERAL_GOV],
    "mountain": [_MOUNTAIN_GOV, _WEATHER_GOV, _GENERAL_GOV],
    "ski": [_MOUNTAIN_GOV, _WEATHER_GOV, _GENERAL_GOV],
    "snow": [_MOUNTAIN_GOV, _WEATHER_GOV, _GENERAL_GOV],
    "campus": [_CAMPUS_EDU, _WEATHER_GOV, _GENERAL_GOV],
    "university": [_CAMPUS_EDU, _GENERAL_GOV],
    "construction": [_CONSTRUCTION_GOV, _CITY_GOV, _GENERAL_GOV],
    "infrastructure": [_CONSTRUCTION_GOV, _GENERAL_GOV],
    "flood": [_SAFETY_GOV, _GENERAL_GOV],
    "river": [_SAFETY_GOV, _GENERAL_GOV],
    "emergency": [_SAFETY_GOV, _GENERAL_GOV],
    "fire": [_SAFETY_GOV, _MOUNTAIN_GOV, _GENERAL_GOV],
    "city": [_CITY_GOV, _GENERAL_GOV, _TOURISM, _SAFETY_GOV],
    "downtown": [_CITY_GOV, _GENERAL_GOV, _TOURISM],
    "tourism": [_TOURISM, _GENERAL_GOV, _CITY_GOV],
    # Default / public_live / generic
    "default": [_GENERAL_GOV, _CITY_GOV, _TOURISM, _TRAFFIC_GOV, _SAFETY_GOV],
}


def _intent_key(camera_type_intent: str) -> str:
    """Map a camera_type_intent string to the closest registered key."""
    lowered = (camera_type_intent or "default").casefold()
    for key in _INTENT_MAP:
        if key in lowered:
            return key
    return "default"


def _render_template(template: str, site_scope: str, location: str, safe_exclusions: bool) -> str:
    """Substitute ``{loc}`` and append site scope and optional exclusions."""
    query = template.replace("{loc}", location)
    if site_scope:
        query = f"{query} {site_scope}"
    if safe_exclusions:
        query = f"{query}{_SAFE_EXCLUSIONS}"
    return query


def _site_scopes_for_template(site_scope: str, location: str) -> tuple[str, ...]:
    """Return replacement site scopes for a template's intended source type."""
    if not site_scope:
        return ("",)
    if site_scope == "site:.gov":
        return official_site_scopes_for_location(location, include_global_fallback=True)
    if site_scope == "site:.edu":
        # Keep .edu for campus/weather queries, but allow country-specific
        # official scopes to help non-US locations where education/government
        # ccTLD patterns differ.
        return tuple(dict.fromkeys(("site:.edu", *official_site_scopes_for_location(location, include_global_fallback=False))))
    return (site_scope,)


def _localized_official_queries(camera_type_intent: str, location: str, *, safe_exclusions: bool) -> list[str]:
    """Country/language-aware public-source queries for official/source discovery."""
    terms = localized_camera_terms_for_intent(camera_type_intent, location)
    if not terms:
        return []
    queries: list[str] = []
    for term in terms:
        for site_scope in official_site_scopes_for_location(location, include_global_fallback=False):
            queries.append(_render_template(f'"{term}" "{{loc}}"', site_scope, location, safe_exclusions))
    return queries


def official_source_queries_for_intent(
    camera_type_intent: str,
    location: str,
    *,
    max_queries: int = 20,
    safe_exclusions: bool = True,
) -> list[str]:
    """Return up to ``max_queries`` official-source discovery queries.

    Parameters
    ----------
    camera_type_intent:
        The ``camera_type_intent`` value from ``TargetContext.intent``, e.g.
        ``"traffic"``, ``"weather"``, ``"public_live"``.
    location:
        The canonical target location string (e.g. ``"Atlanta, Georgia"``).
        It is inserted verbatim into the query templates.
    max_queries:
        Maximum number of rendered query strings to return.
    safe_exclusions:
        When ``True`` (default), appends the standard exclusion fragment that
        strips blocked internet-asset search indexes from results.

    Returns
    -------
    list[str]
        Deduplicated, ordered list of ready-to-submit search queries.
    """
    if not location or not location.strip():
        return []

    key = _intent_key(camera_type_intent)
    groups = _INTENT_MAP.get(key, _INTENT_MAP["default"])

    loc = location.strip()
    seen: set[str] = set()
    queries: list[str] = []

    # Country/language-aware terms are inserted first so small query budgets
    # still include Mexico/Ukraine/etc. specific public-source vocabulary.
    for rendered in _localized_official_queries(camera_type_intent, loc, safe_exclusions=safe_exclusions):
        if rendered not in seen:
            seen.add(rendered)
            queries.append(rendered)
        if len(queries) >= max_queries:
            return queries

    for group in groups:
        for template, site_scope in group:
            for scoped in _site_scopes_for_template(site_scope, loc):
                rendered = _render_template(template, scoped, loc, safe_exclusions)
                if rendered not in seen:
                    seen.add(rendered)
                    queries.append(rendered)
                if len(queries) >= max_queries:
                    return queries
    return queries


def official_source_dork_queries_for_intent(
    camera_type_intent: str,
    location: str,
    *,
    max_queries: int = 8,
) -> list[str]:
    """Subset of official-source queries suitable for the dorking budget.

    This returns only the ``.gov`` and ``.edu`` site-scoped entries from the
    intent-appropriate groups, which are the highest-signal official-source
    discovery dorks.  They respect the same safe-exclusion and safety rules
    as the full query set.
    """
    all_queries = official_source_queries_for_intent(
        camera_type_intent,
        location,
        max_queries=max_queries * 4,
        safe_exclusions=True,
    )
    # Keep only scoped public-source queries.  This includes location-specific
    # official domains such as site:.gob.mx and site:.gov.ua, not only US .gov.
    scoped = [q for q in all_queries if "site:." in q]
    return scoped[:max_queries]
