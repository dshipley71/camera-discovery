"""Location-aware search profile helpers for camera-discovery.

These helpers keep camera discovery location-agnostic while still improving
international searches.  They do not validate geometry, scope, or trust.  They
only provide public-source discovery hints such as country-code site scopes and
localized camera terms.

Safety boundary: these helpers must only produce curated public/official source
queries.  They must not emit exposed device-interface dorks, admin/login pages,
default credential terms, private IP ranges, or internet-asset search indexes.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class LocationSearchProfile:
    """Search hints derived from a location string or user query."""

    country_name: str | None = None
    country_code: str | None = None
    official_site_scopes: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    localized_terms: dict[str, tuple[str, ...]] | None = None


_BLOCKED_SITE_EXCLUSIONS: tuple[str, ...] = (
    "-site:insecam.org",
    "-site:shodan.io",
    "-site:censys.io",
    "-site:zoomeye.org",
    "-site:fofa.info",
)

# ISO 3166-1 alpha-2 codes for broad location-context extraction.  The explicit
# country profiles below add language/camera-search details where we have a safe
# curated vocabulary; this table is intentionally used only for generic ccTLD
# expansion and location context, not for trust or scope decisions.
_COUNTRY_CODES: dict[str, str] = {
    "afghanistan": "af", "albania": "al", "algeria": "dz", "andorra": "ad", "angola": "ao",
    "argentina": "ar", "armenia": "am", "australia": "au", "austria": "at", "azerbaijan": "az",
    "bahamas": "bs", "bahrain": "bh", "bangladesh": "bd", "barbados": "bb", "belarus": "by",
    "belgium": "be", "belize": "bz", "benin": "bj", "bhutan": "bt", "bolivia": "bo",
    "bosnia and herzegovina": "ba", "botswana": "bw", "brazil": "br", "brunei": "bn", "bulgaria": "bg",
    "burkina faso": "bf", "burundi": "bi", "cambodia": "kh", "cameroon": "cm", "canada": "ca",
    "chile": "cl", "china": "cn", "colombia": "co", "costa rica": "cr", "croatia": "hr",
    "cuba": "cu", "cyprus": "cy", "czech republic": "cz", "czechia": "cz", "denmark": "dk",
    "dominican republic": "do", "ecuador": "ec", "egypt": "eg", "el salvador": "sv", "estonia": "ee",
    "finland": "fi", "france": "fr", "georgia": "ge", "germany": "de", "ghana": "gh",
    "greece": "gr", "guatemala": "gt", "honduras": "hn", "hungary": "hu", "iceland": "is",
    "india": "in", "indonesia": "id", "ireland": "ie", "israel": "il", "italy": "it",
    "jamaica": "jm", "japan": "jp", "jordan": "jo", "kazakhstan": "kz", "kenya": "ke",
    "kuwait": "kw", "latvia": "lv", "lebanon": "lb", "lithuania": "lt", "luxembourg": "lu",
    "malaysia": "my", "mexico": "mx", "méxico": "mx", "moldova": "md", "morocco": "ma",
    "netherlands": "nl", "new zealand": "nz", "nicaragua": "ni", "nigeria": "ng", "norway": "no",
    "panama": "pa", "peru": "pe", "philippines": "ph", "poland": "pl", "portugal": "pt",
    "romania": "ro", "russia": "ru", "russian federation": "ru", "saudi arabia": "sa", "serbia": "rs",
    "singapore": "sg", "slovakia": "sk", "slovenia": "si", "south africa": "za", "south korea": "kr",
    "spain": "es", "sweden": "se", "switzerland": "ch", "taiwan": "tw", "thailand": "th",
    "turkey": "tr", "türkiye": "tr", "ukraine": "ua", "united arab emirates": "ae",
    "united kingdom": "gb", "great britain": "gb", "england": "gb", "scotland": "gb", "wales": "gb",
    "united states": "us", "united states of america": "us", "usa": "us", "vietnam": "vn", "viet nam": "vn",
}

_COUNTRY_ALIASES: dict[str, str] = {
    "mx": "Mexico", "mex": "Mexico", "méxico": "Mexico", "mexico": "Mexico",
    "ua": "Ukraine", "ukraine": "Ukraine", "україна": "Ukraine", "украина": "Ukraine",
    "us": "United States", "usa": "United States", "united states": "United States", "united states of america": "United States",
    "uk": "United Kingdom", "gb": "United Kingdom", "great britain": "United Kingdom", "united kingdom": "United Kingdom",
}

_PROFILE_BY_COUNTRY: dict[str, LocationSearchProfile] = {
    "mexico": LocationSearchProfile(
        country_name="Mexico",
        country_code="mx",
        official_site_scopes=("site:.gob.mx", "site:.mx"),
        languages=("es", "en"),
        aliases=("mexico", "méxico", "mx", "ciudad de méxico", "mexico city"),
        localized_terms={
            "default": (
                "cámaras en vivo", "camaras en vivo", "cámaras públicas", "camaras publicas",
                "webcams en vivo", "cámara en vivo", "camara en vivo", "mapa de cámaras",
            ),
            "traffic": (
                "cámaras de tráfico", "camaras de trafico", "cámaras viales", "camaras viales",
                "monitoreo vial", "cámaras de tránsito", "camaras de transito", "tránsito cámaras",
                "carreteras cámaras", "autopistas cámaras",
            ),
            "weather": ("cámaras meteorológicas", "camaras meteorologicas", "cámara del clima", "camara del clima"),
            "airport": ("cámara de aeropuerto", "camara de aeropuerto", "cámara de pista", "camara de pista"),
            "beach": ("cámara de playa", "camara de playa", "playa webcam", "cámara de surf", "camara de surf"),
            "harbor": ("cámara de puerto", "camara de puerto", "cámara de marina", "camara de marina"),
            "city": ("cámara de ciudad", "camara de ciudad", "cámara municipal", "camara municipal"),
        },
    ),
    "ukraine": LocationSearchProfile(
        country_name="Ukraine",
        country_code="ua",
        official_site_scopes=("site:.gov.ua", "site:.ua"),
        languages=("uk", "en"),
        aliases=("ukraine", "ua", "україна", "київ", "kyiv", "kiev"),
        localized_terms={
            "default": ("камери онлайн", "вебкамери", "онлайн камери", "live webcams", "public cameras"),
            "traffic": ("дорожні камери", "камери дорожнього руху", "трафік камери", "traffic cameras"),
            "weather": ("погодні камери", "метеокамери", "weather cameras"),
            "city": ("міські камери", "камери міста", "city webcams"),
        },
    ),
    "united states": LocationSearchProfile(
        country_name="United States",
        country_code="us",
        official_site_scopes=("site:.gov", "site:.edu"),
        languages=("en",),
        aliases=("united states", "usa", "us"),
        localized_terms={},
    ),
    "united kingdom": LocationSearchProfile(
        country_name="United Kingdom",
        country_code="gb",
        official_site_scopes=("site:.gov.uk", "site:.ac.uk", "site:.uk"),
        languages=("en",),
        aliases=("united kingdom", "uk", "great britain", "england", "scotland", "wales"),
        localized_terms={},
    ),
}

_GENERIC_CAMERA_TERMS_BY_INTENT: dict[str, tuple[str, ...]] = {
    "default": ("public cameras", "live cameras", "live webcams", "camera map", "camera feed json"),
    "traffic": ("traffic cameras", "road cameras", "highway cameras", "traffic camera map", "road conditions cameras"),
    "weather": ("weather cameras", "weather webcam", "live weather camera"),
    "airport": ("airport cameras", "airport weather camera", "runway camera"),
    "beach": ("beach cameras", "surf camera", "beach webcam"),
    "harbor": ("harbor cameras", "port cameras", "marina cameras"),
    "city": ("city webcam", "downtown camera", "municipal camera"),
}

_US_STATES: tuple[str, ...] = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
    "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi", "missouri",
    "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
)


def country_code_from_location(location: str) -> str | None:
    """Return an ISO alpha-2 country code when a location string names a country."""
    text = _normalize(location)
    if not text:
        return None
    # Longest-name first so "united kingdom" beats "kingdom"-like fragments.
    for name, code in sorted(_COUNTRY_CODES.items(), key=lambda item: len(item[0]), reverse=True):
        if _contains_phrase(text, name):
            return code
    for token in re.findall(r"\b[a-z]{2,3}\b", text):
        if token in _COUNTRY_ALIASES:
            alias = _COUNTRY_ALIASES[token].casefold()
            return _COUNTRY_CODES.get(alias)
    return None


def location_search_profile(location: str) -> LocationSearchProfile:
    """Infer search hints for a location string without deciding scope/trust."""
    text = _normalize(location)
    if not text:
        return LocationSearchProfile()
    for profile_key, profile in _PROFILE_BY_COUNTRY.items():
        aliases = profile.aliases or (profile_key,)
        if any(_contains_phrase(text, alias) for alias in aliases):
            return profile
    if any(_contains_phrase(text, state) for state in _US_STATES):
        return _PROFILE_BY_COUNTRY["united states"]
    code = country_code_from_location(location)
    if code:
        canonical = next((name.title() for name, cc in _COUNTRY_CODES.items() if cc == code), None)
        scopes = tuple(_dedupe([f"site:.gov.{code}", f"site:.{code}"]))
        return LocationSearchProfile(country_name=canonical, country_code=code, official_site_scopes=scopes, languages=("en",), localized_terms={})
    return LocationSearchProfile()


def official_site_scopes_for_location(location: str, *, include_global_fallback: bool = True) -> tuple[str, ...]:
    """Return public-source site scopes ordered from location-specific to generic."""
    profile = location_search_profile(location)
    scopes: list[str] = list(profile.official_site_scopes)
    if include_global_fallback:
        scopes.extend(["site:.gov", "site:.edu"])
    return tuple(_dedupe(scopes))


def localized_camera_terms_for_intent(camera_type_intent: str, location: str, *, include_generic: bool = False) -> tuple[str, ...]:
    """Return localized camera/source terms for a location and camera intent."""
    key = _intent_key(camera_type_intent)
    profile = location_search_profile(location)
    terms: list[str] = []
    localized = profile.localized_terms or {}
    terms.extend(localized.get(key, ()))
    if key != "default":
        terms.extend(localized.get("default", ()))
    if include_generic:
        terms.extend(_GENERIC_CAMERA_TERMS_BY_INTENT.get(key, ()))
        if key != "default":
            terms.extend(_GENERIC_CAMERA_TERMS_BY_INTENT.get("default", ()))
    return tuple(_dedupe([term for term in terms if term]))


def safe_exclusion_fragment() -> str:
    return " " + " ".join(_BLOCKED_SITE_EXCLUSIONS)


def _intent_key(camera_type_intent: str) -> str:
    lowered = (camera_type_intent or "default").replace("_", " ").casefold()
    for key in ("traffic", "weather", "airport", "beach", "harbor", "port", "marina", "city"):
        if key in lowered:
            return key
    return "default"


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    phrase = _normalize(phrase)
    if not phrase:
        return False
    return bool(re.search(rf"(?<![\w]){re.escape(phrase)}(?![\w])", text, flags=re.I | re.UNICODE))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out
