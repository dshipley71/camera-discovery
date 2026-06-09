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
    attempts = [diag for diag in diagnostics if diag.get("query_key")]
    assert {(diag["engine"], diag["query_type"], diag["query"]) for diag in attempts if diag.get("attempted")} == {
        ("ddg", "normal", "public cameras"),
        ("bing", "normal", "public cameras"),
        ("searxng", "normal", "public cameras"),
    }
    assert all(diag["query_key"].startswith(f"{diag['engine']}|{diag['query_type']}|") for diag in attempts)


def test_dork_queries_run_through_ddg_and_bing_without_searxng(monkeypatch, tmp_path):
    policy = load_source_policy(None, [])
    cfg = SimpleNamespace(
        max_search_results_per_query=10,
        search_engines=["ddg", "bing", "searxng"],
        searxng_base_url="",
        searxng_categories="general",
        searxng_max_results=10,
        user_agent="test",
        http_timeout=1.0,
        ddg_delay_seconds=0.0,
    )
    dispatcher = SearchDispatcher(cfg, policy, tmp_path)
    seen = {"ddg": [], "bing": []}

    def ddg(query):
        seen["ddg"].append(query)
        return [{"query": query, "url": "https://example.gov/ddg", "title": "DDG", "source_provider": "blind:ddg", "search_engine": "ddg"}]

    def bing(query):
        seen["bing"].append(query)
        return [{"query": query, "url": "https://example.gov/bing", "title": "Bing", "source_provider": "blind:bing", "search_engine": "bing"}]

    monkeypatch.setattr(dispatcher, "_ddg_search", ddg)
    monkeypatch.setattr(dispatcher, "_bing_search", bing)
    monkeypatch.setattr(dispatcher, "_searxng_search", lambda query: (_ for _ in ()).throw(AssertionError("SearXNG should be skipped when base URL is missing")))

    rows, diagnostics = dispatcher.search_all(["site:.gov public cameras"])

    assert seen == {"ddg": ["site:.gov public cameras"], "bing": ["site:.gov public cameras"]}
    assert {row["search_engine"] for row in rows} == {"ddg", "bing"}
    dork_attempts = [diag for diag in diagnostics if diag.get("query_type") == "dork"]
    assert {diag["engine"] for diag in dork_attempts} == {"ddg", "bing", "searxng"}
    assert all(diag.get("skip_reason") != "searxng_base_url_not_configured" for diag in dork_attempts if diag["engine"] in {"ddg", "bing"})
    searxng = next(diag for diag in dork_attempts if diag["engine"] == "searxng")
    assert searxng["status"] == "not_configured"
    assert searxng["skip_reason"] == "searxng_base_url_not_configured"


def test_query_attempt_deduplication_is_engine_and_type_aware(monkeypatch, tmp_path):
    policy = load_source_policy(None, [])
    cfg = SimpleNamespace(
        max_search_results_per_query=10,
        search_engines=["ddg", "bing"],
        searxng_base_url="",
        searxng_categories="general",
        searxng_max_results=10,
        user_agent="test",
        http_timeout=1.0,
        ddg_delay_seconds=0.0,
    )
    dispatcher = SearchDispatcher(cfg, policy, tmp_path)
    calls = []

    def engine_rows(engine):
        def inner(query):
            calls.append((engine, query))
            return [{"query": query, "url": f"https://example.gov/{engine}/{len(calls)}", "title": engine, "source_provider": f"blind:{engine}", "search_engine": engine}]
        return inner

    monkeypatch.setattr(dispatcher, "_ddg_search", engine_rows("ddg"))
    monkeypatch.setattr(dispatcher, "_bing_search", engine_rows("bing"))

    _, diagnostics = dispatcher.search_all(["public cameras", "  public   cameras  ", "site:.gov public cameras", "site:.gov  public   cameras"])

    assert sorted(calls) == sorted([
        ("ddg", "public cameras"),
        ("bing", "public cameras"),
        ("ddg", "site:.gov public cameras"),
        ("bing", "site:.gov public cameras"),
    ])
    duplicates = [diag for diag in diagnostics if diag.get("status") == "duplicate_suppressed"]
    assert len(duplicates) == 4
    summary = next(diag for diag in diagnostics if diag.get("record_type") == "query_plan_summary")
    assert summary["duplicate_query_attempts_suppressed"] == 4
    attempted = [diag for diag in diagnostics if diag.get("attempted")]
    assert {(diag["engine"], diag["query_type"], diag["normalized_query"]) for diag in attempted} == {
        ("ddg", "normal", "public cameras"),
        ("bing", "normal", "public cameras"),
        ("ddg", "dork", "site:.gov public cameras"),
        ("bing", "dork", "site:.gov public cameras"),
    }


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
        {
            "engine": "ddg",
            "query_type": "normal",
            "query": "q",
            "normalized_query": "q",
            "query_key": "ddg|normal|q",
            "configured": True,
            "attempted": True,
            "status": "ran",
            "results_seen": 2,
            "parsed_rows": 2,
            "selected_rows": 1,
            "blocked_rows": 0,
            "duplicate_rows": 1,
            "error_count": 0,
        },
        {
            "engine": "bing",
            "query_type": "dork",
            "query": "site:.gov q",
            "normalized_query": "site:.gov q",
            "query_key": "bing|dork|site:.gov q",
            "configured": True,
            "attempted": True,
            "status": "ran",
            "results_seen": 0,
            "parsed_rows": 0,
            "selected_rows": 0,
            "blocked_rows": 0,
            "duplicate_rows": 0,
            "error_count": 0,
        },
        {
            "engine": "searxng",
            "query_type": "dork",
            "query": "site:.gov q",
            "normalized_query": "site:.gov q",
            "query_key": "searxng|dork|site:.gov q",
            "configured": False,
            "attempted": False,
            "status": "not_configured",
            "skip_reason": "searxng_base_url_not_configured",
            "results_seen": 0,
            "parsed_rows": 0,
            "selected_rows": 0,
            "blocked_rows": 0,
            "duplicate_rows": 0,
            "error_count": 0,
        },
    ]
    selected = [{"url": "https://example.gov/cameras", "source_provider": "blind:ddg", "search_engine": "ddg"}]
    summary = build_search_service_summary(diagnostics, selected, [])
    assert {"ddg", "bing", "searxng", "google", "global"}.issubset(summary)
    assert "google_dork" not in summary
    assert summary["ddg"]["selected_rows"] == 1
    assert summary["ddg"]["normal_queries_attempted"] == 1
    assert summary["bing"]["attempted"] is True
    assert summary["bing"]["dork_queries_attempted"] == 1
    assert summary["searxng"]["status"] == "not_configured"
    assert summary["searxng"]["skip_reason"] == "searxng_base_url_not_configured"
    assert summary["google"]["status"] == "unsupported_backend"
    assert summary["google"]["skip_reason"] == "google_backend_not_configured"
    assert summary["global"]["dork_queries_attempted"] == 1

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
    assert source_summary["blind_search_queries"] == ["q", "site:.gov q"]
    assert source_summary["blind_search_results_by_query"]["ddg"]["normal"]["q"]["parsed_rows"] == 2
    assert source_summary["blind_search_results_by_query"]["bing"]["dork"]["site:.gov q"]["parsed_rows"] == 0


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
