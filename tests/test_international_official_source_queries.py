from camera_discovery.discovery.locations import (
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
