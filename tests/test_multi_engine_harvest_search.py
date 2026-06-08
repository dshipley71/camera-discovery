from pathlib import Path
from types import SimpleNamespace

from camera_discovery.discovery.search.bing import parse_bing_results
from camera_discovery.discovery.search.dispatcher import SearchDispatcher
from camera_discovery.discovery.search.searxng import parse_searxng_results
from camera_discovery.extraction.endpoints import extract_endpoint_urls_from_text
from camera_discovery.harvest.records import harvest_search_queries
from camera_discovery.sources import load_source_policy


def test_harvest_search_queries_include_official_source_expansion():
    queries = harvest_search_queries("California traffic cameras", 12)
    assert any("site:.gov" in query for query in queries)
    assert any("traffic cameras" in query and "-site:insecam.org" in query for query in queries)


def test_bing_and_searxng_parsers_return_normalized_rows():
    bing = parse_bing_results(
        '<li class="b_algo"><h2><a href="https://example.gov/cameras">Camera Map</a></h2>'
        '<p>Official traffic cameras</p></li>',
        query="camera query",
    )
    assert bing[0]["url"] == "https://example.gov/cameras"
    assert bing[0]["source_provider"] == "blind:bing"
    assert bing[0]["search_engine"] == "bing"

    searx = parse_searxng_results(
        {"results": [{"url": "https://example.gov/api/cameras.json", "title": "API", "content": "camera json"}]},
        query="camera query",
    )
    assert searx[0]["url"].endswith("/api/cameras.json")
    assert searx[0]["source_provider"] == "blind:searxng"
    assert searx[0]["search_engine"] == "searxng"


def test_search_dispatcher_merges_engines_without_network(monkeypatch, tmp_path):
    policy = load_source_policy(None, [])
    cfg = SimpleNamespace(
        max_search_results_per_query=10,
        search_engines=["ddg", "bing", "searxng"],
        searxng_base_url="http://localhost:8888",
        searxng_categories="general",
        searxng_max_results=10,
        user_agent="test",
        http_timeout=1.0,
        ddg_delay_seconds=0.0,
    )
    dispatcher = SearchDispatcher(cfg, policy, tmp_path)
    monkeypatch.setattr(dispatcher, "_ddg_search", lambda query: [{"query": query, "url": "https://example.gov/cameras", "title": "A", "source_provider": "blind:ddg", "search_engine": "ddg"}])
    monkeypatch.setattr(dispatcher, "_bing_search", lambda query: [{"query": query, "url": "https://example.gov/cameras", "title": "A2", "source_provider": "blind:bing", "search_engine": "bing"}])
    monkeypatch.setattr(dispatcher, "_searxng_search", lambda query: [{"query": query, "url": "https://example.gov/api", "title": "B", "source_provider": "blind:searxng", "search_engine": "searxng"}])

    rows, diagnostics = dispatcher.search_all(["public cameras"])

    assert {row["url"] for row in rows} == {"https://example.gov/cameras", "https://example.gov/api"}
    merged = next(row for row in rows if row["url"] == "https://example.gov/cameras")
    assert merged["source_provider"] == "blind:multi"
    assert set(merged["search_engines"]) == {"ddg", "bing"}
    assert any(diag.get("ddg_count") == 1 and diag.get("bing_count") == 1 for diag in diagnostics)


def test_xhr_fetch_endpoint_extraction_covers_common_javascript_forms():
    html = """
    <script>
      fetch('/api/cameras.json');
      $.getJSON('/feed/cameras');
      axios.get('/arcgis/rest/services/CCTV/FeatureServer/0/query?f=json');
      xhr.open("GET", "/data/cameras.geojson");
      $.ajax({url: '/layers/cameraLayer'});
    </script>
    """
    urls = extract_endpoint_urls_from_text(html, "https://agency.example.gov/map")
    assert "https://agency.example.gov/api/cameras.json" in urls
    assert "https://agency.example.gov/feed/cameras" in urls
    assert "https://agency.example.gov/arcgis/rest/services/CCTV/FeatureServer/0/query?f=json" in urls
    assert "https://agency.example.gov/data/cameras.geojson" in urls
    assert "https://agency.example.gov/layers/cameraLayer" in urls


def test_search_service_summary_keeps_zero_and_skipped_services():
    from camera_discovery.harvest.outputs import build_search_service_summary, build_source_rows_summary
    from camera_discovery.core.models import DiscoveryMode, HarvestConfig

    diagnostics = [
        {"query": "q", "engine": "ddg", "parsed_rows": 2},
        {"query": "q", "engine": "bing", "parsed_rows": 0},
        {"query": "q", "engine": "searxng", "skipped": True, "reason": "searxng_base_url_not_configured"},
        {"query": "site:.gov q", "engine": "ddg", "parsed_rows": 0},
    ]
    selected = [{"url": "https://example.gov/cameras", "source_provider": "blind:ddg", "search_engine": "ddg"}]
    summary = build_search_service_summary(diagnostics, selected, [])
    assert set(summary) == {"ddg", "bing", "searxng", "google_dork"}
    assert summary["ddg"]["selected_rows"] == 1
    assert summary["bing"]["attempted"] is True
    assert summary["bing"]["parsed_rows"] == 0
    assert summary["searxng"]["status"] == "not_configured"
    assert summary["google_dork"]["attempted"] is True
    assert summary["google_dork"]["parsed_rows"] == 0

    cfg = HarvestConfig(query="q", output_dir=Path("/tmp/out"), discovery_mode=DiscoveryMode.BOTH)
    source_summary = build_source_rows_summary(
        config=cfg,
        source_policy=load_source_policy(None, []),
        directory_rows=[],
        blind_rows=selected,
        direct_rows=[],
        selected_before_budget=selected,
        selected=selected,
        blocked_rows=[],
        max_source_rows_applied=False,
        blind_search_diagnostics=diagnostics,
    )
    assert source_summary["selected_blind_rows"] == 1
    assert source_summary["selected_by_provider"]["blind:ddg"] == 1


def test_endpoint_noise_filter_keeps_camera_json_and_drops_analytics():
    from camera_discovery.extraction.endpoints import extract_endpoint_urls_from_text, linked_script_urls_from_html

    html = '<script src="https://www.googletagmanager.com/gtm.js?id=GTM-1"></script><script src="/static/app.js"></script>'
    scripts = linked_script_urls_from_html(html, "https://agency.example.gov/map")
    assert "https://www.googletagmanager.com/gtm.js?id=GTM-1" not in scripts
    assert "https://agency.example.gov/static/app.js" in scripts
    js = "fetch('/api/cameras.json'); fetch('https://www.google-analytics.com/collect?f=json')"
    urls = extract_endpoint_urls_from_text(js, "https://agency.example.gov/app.js")
    assert "https://agency.example.gov/api/cameras.json" in urls
    assert not any("google-analytics" in url for url in urls)
