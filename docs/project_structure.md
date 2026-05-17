# Project Structure

```text
camera-discovery/
  pyproject.toml
  README.md
  .env.example
  Makefile
  src/camera_discovery/
    cli.py
    core/
      config.py
      models.py
    llm/
      base.py
      factory.py
      ollama.py
      openai_compatible.py
      bedrock.py
    services/
      target_resolver.py
      discovery_engine.py
      review_validation_pipeline.py
    utils/
      io.py
      json_utils.py
      geojson_viewer.py
    sources/
      __init__.py
      models.py
      registry.py
  tests/
  notebooks/
    camera_discovery_live_test.ipynb
  agents/
```

Keep the CLI thin. The services own business logic. `RunState` is the single source of truth.

## Source Registry Additions

```text
SOURCES.md
src/camera_discovery/sources/
  __init__.py
  models.py
  registry.py
```

`SOURCES.md` allowed entries are directory discovery inputs. Blocked entries are a global deny policy applied to all discovery modes.
