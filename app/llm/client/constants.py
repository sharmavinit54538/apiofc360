"""Ollama LLM client constants and supported models."""

SUPPORTED_MODELS = {
    "llama3",
    "llama3.1",
    "llama3.2",
    "llama3:8b",
    "llama3:70b",
    "qwen2.5",
    "qwen2.5:7b",
    "qwen2.5:14b",
    "qwen2.5:72b",
    "mistral",
    "mistral:7b",
    "deepseek-r1",
    "deepseek-r1:7b",
    "deepseek-r1:14b",
    "phi4",
    "phi4:14b",
    "gemma",
    "gemma:2b",
    "gemma:7b",
    "gemma2",
    "gemma2:9b",
    "nomic-embed-text",
}

_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.5  # seconds
