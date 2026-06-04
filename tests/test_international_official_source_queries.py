from camera_discovery.discovery.location_profiles import (
    country_code_from_location,
    localized_camera_terms_for_intent,
    official_site_scopes_for_location,
)
from camera_discovery.discovery.official_source_queries import official_source_dork_queries_for_intent, official_source_queries_for_intent
from camera_discovery.discovery.search_dispatch import _is_safe_google_dork
from camera_discovery.harvest.records import harvest_search_queries


def test_mexico_official_source_queries_are_country_and_language_aware():
    queries = official_source_queries_for_intent("traffic", "Mexico City, Mexico", max_queries=12)
    assert any("site:.gob.mx" in query for query in queries)
    assert any("cámaras" in query or "camaras" in query for query in queries)
    assert any("monitoreo vial" in query or "cámaras viales" in query for query in queries)
    assert all("insecam" in query and "shodan" in query for query in queries if "site:." in query)


def test_ukraine_official_source_queries_are_country_and_language_aware():
    queries = official_source_queries_for_intent("traffic", "Kyiv, Ukraine", max_queries=12)
    assert any("site:.gov.ua" in query or "site:.ua" in query for query in queries)
    assert any("дорож" in query or "камер" in query for query in queries)


def test_location_profile_country_codes_and_scopes_are_generic():
    assert country_code_from_location("all media in Mexico") == "mx"
    assert country_code_from_location("Kyiv, Ukraine public cameras") == "ua"
    assert "site:.mx" in official_site_scopes_for_location("Mexico")
    assert "site:.gov.ua" in official_site_scopes_for_location("Ukraine")


def test_harvest_queries_include_mexico_localized_terms_and_official_domains():
    queries = harvest_search_queries("Mexico City, Mexico public cameras", 16)
    assert any("cámaras" in query or "camaras" in query for query in queries)
    assert any("site:.gob.mx" in query or "site:.mx" in query for query in queries)


def test_official_dork_queries_include_country_specific_scopes_without_device_dorks():
    queries = official_source_dork_queries_for_intent("traffic", "Mexico City, Mexico", max_queries=8)
    assert any("site:.gob.mx" in query for query in queries)
    assert all("axis-cgi" not in query.casefold() and "password" not in query.casefold() for query in queries)
    assert all(_is_safe_google_dork(query) for query in queries)


def test_localized_terms_do_not_require_mexico_specific_workflow():
    assert localized_camera_terms_for_intent("traffic", "Mexico")
    assert localized_camera_terms_for_intent("traffic", "Ukraine")


def test_location_profile_module_boundaries_are_current() -> None:
    import importlib.util
    from pathlib import Path

    import camera_discovery

    root = Path(camera_discovery.__file__).resolve().parent
    assert (root / "geo" / "location_profiles.py").exists()
    assert (root / "discovery" / "location_profiles.py").exists()
    assert (root / "enrichment" / "location_evidence.py").exists()
    assert not (root / "discovery" / "locations.py").exists()
    assert not (root / "enrichment" / "location.py").exists()

    assert importlib.util.find_spec("camera_discovery.geo.location_profiles") is not None
    assert importlib.util.find_spec("camera_discovery.discovery.location_profiles") is not None
    assert importlib.util.find_spec("camera_discovery.enrichment.location_evidence") is not None


def test_first_and_second_batch_country_profiles_have_scopes_and_terms():
    expected = {
        "Canada": "site:.gc.ca",
        "Australia": "site:.gov.au",
        "New Zealand": "site:.govt.nz",
        "Brazil": "site:.gov.br",
        "Chile": "site:.gob.cl",
        "Argentina": "site:.gob.ar",
        "Colombia": "site:.gov.co",
        "Spain": "site:.gob.es",
        "France": "site:.gouv.fr",
        "Germany": "site:.bund.de",
        "Japan": "site:.go.jp",
        "South Korea": "site:.go.kr",
        "Taiwan": "site:.gov.tw",
        "Singapore": "site:.gov.sg",
        "India": "site:.gov.in",
        "Netherlands": "site:.overheid.nl",
        "Norway": "site:.vegvesen.no",
        "Sweden": "site:.trafikverket.se",
        "Finland": "site:.fintraffic.fi",
        "Poland": "site:.gov.pl",
        "Italy": "site:.gov.it",
        "Portugal": "site:.gov.pt",
        "South Africa": "site:.gov.za",
        "United Arab Emirates": "site:.gov.ae",
        "Israel": "site:.gov.il",
        "Thailand": "site:.go.th",
        "Indonesia": "site:.go.id",
        "Philippines": "site:.gov.ph",
        "Malaysia": "site:.gov.my",
    }
    for location, scope in expected.items():
        assert scope in official_site_scopes_for_location(location), location
        assert localized_camera_terms_for_intent("traffic", location), location


def test_asian_arabic_and_russia_profiles_generate_safe_public_source_dorks():
    expected = {
        "Japan": ("site:.go.jp", "カメラ"),
        "China": ("site:.gov.cn", "摄像"),
        "Hong Kong": ("site:.gov.hk", "traffic"),
        "Vietnam": ("site:.gov.vn", "camera"),
        "Saudi Arabia": ("site:.gov.sa", "كاميرات"),
        "Egypt": ("site:.gov.eg", "كاميرات"),
        "Russia": ("site:.gov.ru", "камер"),
    }
    for location, (scope, term_fragment) in expected.items():
        queries = official_source_dork_queries_for_intent("traffic", location, max_queries=6)
        assert any(scope in query for query in queries), location
        assert any(term_fragment in query.casefold() for query in queries), location
        assert all(_is_safe_google_dork(query) for query in queries), location


def test_arabic_country_profiles_cover_arab_league_style_locations():
    expected_scopes = {
        "Algeria": "site:.gov.dz",
        "Bahrain": "site:.gov.bh",
        "Comoros": "site:.gouv.km",
        "Djibouti": "site:.gouv.dj",
        "Iraq": "site:.gov.iq",
        "Jordan": "site:.gov.jo",
        "Kuwait": "site:.gov.kw",
        "Lebanon": "site:.gov.lb",
        "Libya": "site:.gov.ly",
        "Mauritania": "site:.gov.mr",
        "Morocco": "site:.gov.ma",
        "Oman": "site:.gov.om",
        "Palestine": "site:.gov.ps",
        "Qatar": "site:.gov.qa",
        "Somalia": "site:.gov.so",
        "Sudan": "site:.gov.sd",
        "Syria": "site:.gov.sy",
        "Tunisia": "site:.gov.tn",
        "United Arab Emirates": "site:.gov.ae",
        "Yemen": "site:.gov.ye",
    }
    for location, scope in expected_scopes.items():
        assert scope in official_site_scopes_for_location(location), location
        assert localized_camera_terms_for_intent("traffic", location), location
