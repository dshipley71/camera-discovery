from camera_discovery.extraction.search import clean_ddg_result_url, parse_ddg_result_rows


def test_clean_ddg_result_url_unwraps_absolute_redirect():
    href = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fpublic.example%2Fcameras%3Fq%3D1&rut=abc"
    assert clean_ddg_result_url(href) == "https://public.example/cameras?q=1"


def test_clean_ddg_result_url_rejects_internal_ddg_navigation():
    assert clean_ddg_result_url("https://duckduckgo.com/about") == ""
    assert clean_ddg_result_url("/settings") == ""


def test_parse_ddg_result_rows_supports_classic_result_markup():
    html = '''
    <html><body>
      <a class="result__a" href="/l/?uddg=https%3A%2F%2Fpublic.example%2Fcameras">Public cameras</a>
    </body></html>
    '''
    rows = parse_ddg_result_rows("public cameras", html, max_results=10, include_source_kind=True)
    assert rows == [
        {
            "query": "public cameras",
            "title": "Public cameras",
            "url": "https://public.example/cameras",
            "snippet": "",
            "source_provider": "blind",
            "source_name": "DuckDuckGo",
            "source_kind": "search_result",
        }
    ]


def test_parse_ddg_result_rows_supports_modern_result_markup():
    html = '''
    <html><body>
      <article>
        <h2><a data-testid="result-title-a" href="https://agency.example/traffic-cameras">Traffic cams</a></h2>
      </article>
    </body></html>
    '''
    rows = parse_ddg_result_rows("traffic cameras", html, max_results=10)
    assert rows[0]["url"] == "https://agency.example/traffic-cameras"
    assert rows[0]["title"] == "Traffic cams"
    assert rows[0]["source_provider"] == "blind"


def test_parse_ddg_result_rows_falls_back_to_uddg_text():
    html = 'noise uddg=https%3A%2F%2Ffallback.example%2Fcamera-map&rut=abc'
    rows = parse_ddg_result_rows("camera map", html, max_results=10)
    assert rows[0]["url"] == "https://fallback.example/camera-map"
