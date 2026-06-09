from __future__ import annotations

from typing import Any

GITHUB_CODE_SEARCH_QUERIES: list[dict[str, Any]] = [
    {"id": "github_hls_public_camera_generic", "provider_family": "github_code", "query": '".m3u8" (camera OR webcam OR cctv OR "traffic camera") NOT is:fork', "camera_type_hint": "mixed", "media_hint": "hls", "risk_level": "safe_public_source_discovery", "enabled": True},
    {"id": "github_image_metadata_coordinates", "provider_family": "github_code", "query": '("streamingVideoURL" OR "currentImageURL" OR "imageDescription") (latitude OR longitude OR lat OR lon) NOT is:fork', "camera_type_hint": "mixed", "media_hint": "image_snapshot", "risk_level": "safe_public_source_discovery", "enabled": True},
    {"id": "github_arcgis_camera_layers", "provider_family": "github_code", "query": '("FeatureServer" OR "MapServer") (camera OR cctv OR webcam OR "traffic camera") NOT is:fork', "camera_type_hint": "mixed", "media_hint": "arcgis", "risk_level": "safe_public_source_discovery", "enabled": True},
    {"id": "github_geojson_traffic_cameras", "provider_family": "github_code", "query": '("traffic cameras" OR "road cameras" OR CCTV) (geojson OR "FeatureCollection") NOT is:fork', "camera_type_hint": "traffic", "media_hint": "structured", "risk_level": "safe_public_source_discovery", "enabled": True},
    {"id": "github_image_refresh_fields", "provider_family": "github_code", "query": '("currentImageUpdateFrequency" OR "referenceImageUpdateFrequency") NOT is:fork', "camera_type_hint": "mixed", "media_hint": "image_snapshot", "risk_level": "safe_public_source_discovery", "enabled": True},
    {"id": "github_camera_status_fields", "provider_family": "github_code", "query": '("cameraStatus" OR "cctvStatus" OR "camera_feed" OR "cameraFeed" OR "cameraUrl" OR "camera_url") NOT is:fork', "camera_type_hint": "mixed", "media_hint": "structured", "risk_level": "safe_public_source_discovery", "enabled": True},
    {"id": "github_geojson_path_camera", "provider_family": "github_code", "query": '(camera OR webcam OR cctv) path:*.geojson NOT is:fork', "camera_type_hint": "mixed", "media_hint": "geojson", "risk_level": "safe_public_source_discovery", "enabled": True},
    {"id": "github_json_path_camera", "provider_family": "github_code", "query": '(camera OR webcam OR cctv) path:*.json NOT is:fork', "camera_type_hint": "mixed", "media_hint": "json", "risk_level": "safe_public_source_discovery", "enabled": True},
    {"id": "github_json_media_fields", "provider_family": "github_code", "query": '(".m3u8" OR "mjpeg" OR "mjpg" OR "currentImageURL" OR "streamingVideoURL") path:*.json NOT is:fork', "camera_type_hint": "mixed", "media_hint": "structured_media", "risk_level": "safe_public_source_discovery", "enabled": True},
    {"id": "github_arcgis_directory_refs", "provider_family": "github_code", "query": '("ArcGIS REST Services Directory" OR "FeatureServer" OR "MapServer") (camera OR cctv OR webcam) NOT is:fork', "camera_type_hint": "mixed", "media_hint": "arcgis", "risk_level": "safe_public_source_discovery", "enabled": True},
    {"id": "github_ogc_geo_refs", "provider_family": "github_code", "query": '("WMS" OR "KML" OR "GeoJSON") (camera OR cctv OR webcam OR "traffic camera") NOT is:fork', "camera_type_hint": "mixed", "media_hint": "structured", "risk_level": "safe_public_source_discovery", "enabled": True},
    {"id": "github_public_camera_coordinates", "provider_family": "github_code", "query": '("public cameras" OR "traffic camera" OR "weather camera" OR webcam) (lat OR lon OR latitude OR longitude) NOT is:fork', "camera_type_hint": "mixed", "media_hint": "structured", "risk_level": "safe_public_source_discovery", "enabled": True},
]

GITHUB_WEB_DORK_QUERIES: list[dict[str, Any]] = [
    {"id": "github_web_hls", "provider_family": "web_dork", "query": 'site:github.com ".m3u8" (camera OR webcam OR cctv OR "traffic camera")', "media_hint": "hls", "enabled": True},
    {"id": "raw_github_web_hls", "provider_family": "web_dork", "query": 'site:raw.githubusercontent.com ".m3u8" (camera OR webcam OR cctv OR "traffic camera")', "media_hint": "hls", "enabled": True},
    {"id": "github_web_image_metadata", "provider_family": "web_dork", "query": 'site:github.com ("streamingVideoURL" OR "currentImageURL" OR "imageDescription") (latitude OR longitude OR lat OR lon)', "media_hint": "image_snapshot", "enabled": True},
    {"id": "raw_github_web_image_metadata", "provider_family": "web_dork", "query": 'site:raw.githubusercontent.com ("streamingVideoURL" OR "currentImageURL" OR "imageDescription") (latitude OR longitude OR lat OR lon)', "media_hint": "image_snapshot", "enabled": True},
    {"id": "github_web_arcgis", "provider_family": "web_dork", "query": 'site:github.com ("FeatureServer" OR "MapServer") (camera OR cctv OR webcam OR "traffic camera")', "media_hint": "arcgis", "enabled": True},
    {"id": "raw_github_web_arcgis", "provider_family": "web_dork", "query": 'site:raw.githubusercontent.com ("FeatureServer" OR "MapServer") (camera OR cctv OR webcam OR "traffic camera")', "media_hint": "arcgis", "enabled": True},
    {"id": "github_web_geojson", "provider_family": "web_dork", "query": 'site:github.com ("FeatureCollection" OR geojson) (camera OR cctv OR webcam OR "traffic camera")', "media_hint": "geojson", "enabled": True},
    {"id": "raw_github_web_geojson", "provider_family": "web_dork", "query": 'site:raw.githubusercontent.com ("FeatureCollection" OR geojson) (camera OR cctv OR webcam OR "traffic camera")', "media_hint": "geojson", "enabled": True},
    {"id": "github_web_refresh", "provider_family": "web_dork", "query": 'site:github.com ("currentImageUpdateFrequency" OR "referenceImageUpdateFrequency") camera', "media_hint": "image_snapshot", "enabled": True},
    {"id": "raw_github_web_refresh", "provider_family": "web_dork", "query": 'site:raw.githubusercontent.com ("currentImageUpdateFrequency" OR "referenceImageUpdateFrequency") camera', "media_hint": "image_snapshot", "enabled": True},
    {"id": "github_web_status_fields", "provider_family": "web_dork", "query": 'site:github.com ("cameraStatus" OR "cctvStatus" OR "camera_feed" OR "cameraFeed" OR "cameraUrl" OR "camera_url")', "media_hint": "structured", "enabled": True},
    {"id": "raw_github_web_status_fields", "provider_family": "web_dork", "query": 'site:raw.githubusercontent.com ("cameraStatus" OR "cctvStatus" OR "camera_feed" OR "cameraFeed" OR "cameraUrl" OR "camera_url")', "media_hint": "structured", "enabled": True},
    {"id": "github_web_geojson_path", "provider_family": "web_dork", "query": 'site:github.com inurl:.geojson (camera OR cctv OR webcam OR "traffic camera")', "media_hint": "geojson", "enabled": True},
    {"id": "github_web_json_media", "provider_family": "web_dork", "query": 'site:github.com inurl:.json (".m3u8" OR "currentImageURL" OR "streamingVideoURL")', "media_hint": "json", "enabled": True},
    {"id": "github_web_csv_coordinates", "provider_family": "web_dork", "query": 'site:github.com inurl:.csv (camera OR cctv OR webcam) (lat OR lon OR latitude OR longitude)', "media_hint": "csv", "enabled": True},
    {"id": "github_web_kml", "provider_family": "web_dork", "query": 'site:github.com inurl:.kml (camera OR cctv OR webcam OR "traffic camera")', "media_hint": "kml", "enabled": True},
    {"id": "github_web_yaml_media", "provider_family": "web_dork", "query": 'site:github.com (inurl:.yml OR inurl:.yaml) (".m3u8" OR "currentImageURL" OR "streamingVideoURL") camera', "media_hint": "yaml", "enabled": True},
    {"id": "github_web_arcgis_directory", "provider_family": "web_dork", "query": 'site:github.com "ArcGIS REST Services Directory" (camera OR cctv OR webcam)', "media_hint": "arcgis", "enabled": True},
    {"id": "github_web_public_cameras", "provider_family": "web_dork", "query": 'site:github.com "public cameras" (".m3u8" OR "FeatureServer" OR "GeoJSON")', "media_hint": "mixed", "enabled": True},
    {"id": "github_web_traffic_cameras", "provider_family": "web_dork", "query": 'site:github.com "traffic cameras" (".m3u8" OR "FeatureServer" OR "MapServer" OR "GeoJSON")', "media_hint": "mixed", "enabled": True},
]
