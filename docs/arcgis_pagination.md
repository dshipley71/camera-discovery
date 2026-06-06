# Shared ArcGIS feature-layer pagination

Camera-discovery uses a shared ArcGIS feature-layer paginator for advertised `MapServer` and `FeatureServer` layers discovered through the structured-endpoint path. ArcGIS services often cap a single `/query` response at the layer `maxRecordCount`; a response may include `exceededTransferLimit: true`, which means additional records exist beyond the first page.

The paginator improves recall for both workflows while preserving their separate semantics:

- `camera-discovery run` still applies target resolution, deterministic scope checks, validation, trust gates, GeoJSON/map output, and review packaging.
- `camera-discovery harvest-urls` remains extraction-only and does not run target resolution, geocoding, validation, trust classification, GeoJSON/map output, `cameras.md`, or review ZIP creation.
- Source blocking from `SOURCES.md` and configured block patterns is checked before metadata, page, and object-ID requests.
- Pagination never marks records trusted, bypasses validation or scope gates, guesses layer IDs, authenticates, scans hosts, or changes English-canonical output schemas.

## Strategies

### Offset pagination

When layer metadata advertises `advancedQueryCapabilities.supportsPagination`, camera-discovery requests bounded `/query` pages with:

- `where=1=1`
- `outFields=*`
- `returnGeometry=true`
- `f=json`
- `resultOffset=<offset>`
- `resultRecordCount=<page_size>`

When `supportsOrderBy` and an object ID field are available, `orderByFields=<object_id_field>` is included for stable ordering.

### Object-ID fallback

When offset pagination is unavailable or unreliable, the shared paginator requests IDs with `returnIdsOnly=true`, then fetches bounded `objectIds=` batches. This fallback is used for layers that do not support pagination, offset capability/parameter errors, repeated pages, and suspicious incomplete offset responses.

## Configuration

Environment variables:

| Variable | Default | Meaning |
| --- | ---: | --- |
| `CAMERA_DISCOVERY_ARCGIS_PAGINATION_STRATEGY` | `auto` | One of `auto`, `offset`, `object_ids`, or `single_page`. |
| `CAMERA_DISCOVERY_ARCGIS_PAGE_SIZE` | `1000` | Offset page size, capped by layer `maxRecordCount` when present. |
| `CAMERA_DISCOVERY_ARCGIS_OBJECT_ID_BATCH_SIZE` | `500` | Object-ID batch size, capped by layer `maxRecordCount` when present. |
| `CAMERA_DISCOVERY_MAX_ARCGIS_PAGES_PER_LAYER` | `100` | Hard page/batch limit to prevent infinite loops. |
| `CAMERA_DISCOVERY_MAX_ARCGIS_RECORDS_PER_LAYER` | `0` | Optional record cap; `0` means no explicit record cap beyond page/batch limits. |

For large harvest inventories, keep `CAMERA_DISCOVERY_ARCGIS_PAGINATION_STRATEGY=auto` and raise `CAMERA_DISCOVERY_MAX_ARCGIS_PAGES_PER_LAYER` only as needed. `harvest-urls` may also use its existing harvest source-row and structured-endpoint budgets; those budgets remain separate from ArcGIS page/batch safety limits.

## Diagnostics

Structured endpoint logs include an `arcgis_pagination` object for paginated ArcGIS layers. It reports the layer URL, metadata URL, object ID field, max record count, support flags, strategy, requested pages, returned and unique feature counts, duplicates, fallback use, response-cache hits, stop reason, and errors.

Stop reasons distinguish complete and truncated retrievals, including `exceeded_transfer_limit_false`, `short_page`, `empty_page`, `repeated_page`, `all_features_seen`, `page_limit_reached`, `record_limit_reached`, `source_blocked`, `query_error`, `object_id_fallback_completed`, `object_id_fallback_error`, and `single_page_strategy`.
