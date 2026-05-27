# SOURCES.md Blueprint

`SOURCES.md` is a user-approved source registry and global block-policy file.

Allowed rows are used only in `directory` and `both` discovery modes. Blind search must not read allowed rows from `SOURCES.md`. Blocked patterns are global and apply to blind search, directory rows, direct seed URLs, fetched pages/endpoints, extracted media URLs, harvest outputs, and final candidates.

## Format

```markdown
## Allowed Sources

| name | url | type | scope_hint | enabled | notes |
|---|---|---|---|---|---|
| Example | https://example.org/cameras | site | global | true | User-approved public source. |

## Blocked Sources

| pattern | reason |
|---|---|
| example-bad-domain.test | Reason this source is not allowed. |
```

## Allowed source types

```text
page        # normal HTML/page source
feed        # feed-like source
direct_hls  # direct HLS playlist source
site        # site/directory entry that may expand to deeper rows
dynamic     # source likely to require browser capture
```

## Scope hints

`scope_hint` is advisory metadata for source-row generation and diagnostics. Use generic values such as:

```text
global
country:<country-code-or-name>
state:<state-or-region>
city:<city-name>
place:<place-name>
```

Do not add source-specific code behavior for a source. If a source requires special handling, first try generic extraction improvements in `extraction/`, `discovery/`, or `harvest/`.

## Defaults and path resolution

The CLI defaults to `SOURCES.md`. When run from outside the repository root, the config loader falls back to the editable repository root's `SOURCES.md` when the current working directory does not contain one. Explicit custom source-file paths are preserved.

## Guardrails

- Do not auto-edit `SOURCES.md` during discovery or harvest.
- Do not treat an allowed source as trusted camera evidence.
- Do not bypass blocked patterns for direct seed URLs or extracted media.
- Do not include internet-connected device search engines or scanning platforms as allowed camera sources.
