# LLM Provider Agent

Maintain one shared provider factory in `src/camera_discovery/llm/factory.py`.

Supported provider values:

```text
ollama
ollama-cloud
openai
openai-compatible
openai_compatible
bedrock
```

Factory functions currently used by runners/services:

```text
build_llm_client
build_target_intent_client
build_geocoder_referee_client
build_location_inference_client
build_candidate_review_client
```

Provider/model overrides must use the same factory path. Do not create stage-specific custom connection logic.

Connection settings:

- Ollama Cloud uses `OLLAMA_BASE_URL` or `https://ollama.com` and `OLLAMA_API_KEY`.
- Local Ollama uses `OLLAMA_BASE_URL` or `http://localhost:11434`.
- OpenAI-compatible uses `OPENAI_COMPATIBLE_BASE_URL`, `OPENAI_COMPATIBLE_API_KEY`, and `/chat/completions`.
- Bedrock uses AWS credentials and `AWS_REGION` / `AWS_DEFAULT_REGION`.

Never log secrets. LLMs remain advisory and must not produce coordinates or trusted inventory.
