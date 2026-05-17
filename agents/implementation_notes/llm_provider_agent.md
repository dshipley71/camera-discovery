# LLM Provider Agent

Implement one shared provider factory for all LLM stages.

Supported providers:

- Ollama / Ollama Cloud `/api/chat`
- OpenAI-compatible `/v1/chat/completions`
- Bedrock Runtime Converse API

Each advisory stage can use a separate model:

- target intent
- geocoder referee
- candidate semantic review

All stages must share connection settings and never log secrets.
