"""OpenAI-compatible model-list response for configured LLM providers."""


def models_response(providers):
    """Expose provider IDs only; never serialize provider configuration."""
    model_ids = sorted({
        name for name in providers
        if isinstance(name, str) and name
    })
    return {
        "object": "list",
        "data": [
            {"id": model_id, "object": "model"}
            for model_id in model_ids
        ],
    }
