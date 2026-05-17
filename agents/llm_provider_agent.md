# 02 — LLM Provider Agent

Implement a shared LLM provider factory.

Providers:

- `ollama` / `ollama-cloud`: `/api/chat`
- `openai-compatible`: `/v1/chat/completions`
- `bedrock`: Bedrock Runtime Converse API

Factory functions:

- `build_llm_client`
- `build_target_intent_client`
- `build_geocoder_referee_client`
- `build_candidate_review_client`

Do not create separate custom connection paths per stage. All stages share provider/base URL/API key behavior.
