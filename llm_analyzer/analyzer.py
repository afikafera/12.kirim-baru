from contextlib import contextmanager
from contextvars import ContextVar
import inspect

from langfuse.openai import OpenAI


class LLMAnalyzer:

    def __init__(self, config: dict):
        self.config = config

        self.default_model = (
            config.get("LLM_DEFAULT_MODEL")
            or config.get("LLM_MODEL")
            or "9router"
        )

        self._request_model = ContextVar(
            "hermes_llm_model",
            default=None,
        )

        self.providers = self._load_providers()

        # Compatibility dengan kode lama.
        self.model = self.default_model

    def _load_providers(self):
        config = self.config
        providers = {}

        # Dynamic provider registry.
        #
        # Expected config:
        #   LLM_PROVIDER_<NAME>_API_KEY
        #   LLM_PROVIDER_<NAME>_BASE_URL
        #   LLM_PROVIDER_<NAME>_MODEL
        #
        # Example:
        #   LLM_PROVIDER_9ROUTER_BASE_URL=...
        #   LLM_PROVIDER_9ROUTER_MODEL=oc/mimo-v2.5-free
        #
        # Provider name exposed to Open WebUI is the lowercase <NAME>.
        prefix = "LLM_PROVIDER_"

        provider_names = set()

        for key in config:
            if not key.startswith(prefix):
                continue

            suffix = key[len(prefix):]

            for field in ("_API_KEY", "_BASE_URL", "_MODEL", "_ALIASES"):
                if suffix.endswith(field):
                    name = suffix[:-len(field)]
                    if name:
                        provider_names.add(name)
                    break

        for name in sorted(provider_names):
            api_key = (
                config.get(f"{prefix}{name}_API_KEY")
                or config.get("LLM_API_KEY")
            )
            base_url = config.get(f"{prefix}{name}_BASE_URL")
            model = config.get(f"{prefix}{name}_MODEL")

            # Provider is valid only when its endpoint and upstream model
            # are configured.
            if not base_url or not model:
                continue

            provider_name = name.lower()

            aliases_raw = config.get(
                f"{prefix}{name}_ALIASES",
                "",
            )
            aliases = {
                alias.strip()
                for alias in aliases_raw.split(",")
                if alias.strip()
            }

            providers[provider_name] = {
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
                "aliases": aliases,
            }

        # Legacy LLM config fallback.
        if not providers and config.get("LLM_BASE_URL"):
            providers["9router"] = {
                "api_key": config.get("LLM_API_KEY"),
                "base_url": config["LLM_BASE_URL"],
                "model": config.get("LLM_MODEL"),
            }

        # Legacy DeepSeek config fallback.
        if config.get("DEEPSEEK_API_KEY"):
            providers.setdefault("deepseek-chat", {
                "api_key": config["DEEPSEEK_API_KEY"],
                "base_url": config.get(
                    "DEEPSEEK_BASE_URL",
                    "https://api.deepseek.com/v1",
                ),
                "model": config.get(
                    "DEEPSEEK_MODEL",
                    "deepseek-chat",
                ),
            })

        return providers

    def _get_provider(self, selected_model=None):
        model_name = (
            selected_model
            or self._request_model.get()
            or self.default_model
        )

        # Resolve selected Open WebUI model through provider configuration.
        # No model/provider aliases are hardcoded here.
        provider_name = None

        for name, provider_config in self.providers.items():
            if model_name == name:
                provider_name = name
                break

            if model_name in provider_config.get("aliases", set()):
                provider_name = name
                break

        if provider_name is None:
            raise ValueError(
                f"Unknown LLM model/provider: {model_name}. "
                f"Available: {', '.join(self.providers.keys())}"
            )

        provider = self.providers[provider_name]

        if provider is None:
            raise ValueError(
                f"Unknown LLM model/provider: {model_name}. "
                f"Available: {', '.join(self.providers.keys())}"
            )

        return provider_name, provider

    @contextmanager
    def use_model(self, model):
        token = self._request_model.set(model)
        try:
            yield
        finally:
            self._request_model.reset(token)

    def analyze(
        self,
        system_prompt: str,
        user_query: str,
        temperature: float = 0.3,
        model=None,
        max_tokens=None,
    ) -> dict:

        selected_name, provider = self._get_provider(model)

        print(
            f"[LLM] selected={selected_name!r} "
            f"upstream={provider['model']!r}",
            flush=True,
        )

        print(
            f"[PROMPT SIZE] chars={len(system_prompt)} "
            f"user={len(user_query)}"
        )

        caller = inspect.stack()[1]
        print(
            f"[LLM CALLER] file={caller.filename} "
            f"line={caller.lineno} function={caller.function}",
            flush=True,
        )

        client = OpenAI(
            api_key=provider["api_key"],
            base_url=provider["base_url"],
            timeout=120.0,
        )

        request_kwargs = {
            "model": provider["model"],
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_query,
                },
            ],
            "temperature": temperature,
        }

        # Optional per-call output budget.
        # None preserves the previous behavior: do not send max_tokens.
        if max_tokens is not None:
            request_kwargs["max_tokens"] = int(max_tokens)

        response = client.chat.completions.create(**request_kwargs)

        # DIAGNOSTIC ONLY: inspect provider response shape before parsing.
        try:
            debug_choices = getattr(response, "choices", None)
            debug_first = (
                debug_choices[0]
                if debug_choices
                else None
            )
            debug_message = (
                getattr(debug_first, "message", None)
                if debug_first is not None
                else None
            )

            print(
                "[LLM RESPONSE DEBUG]",
                {
                    "response_type": type(response).__name__,
                    "choices_type": type(debug_choices).__name__,
                    "choices_len": len(debug_choices) if debug_choices else 0,
                    "first_choice_type": (
                        type(debug_first).__name__
                        if debug_first is not None
                        else None
                    ),
                    "message_type": (
                        type(debug_message).__name__
                        if debug_message is not None
                        else None
                    ),
                    "content_type": (
                        type(getattr(debug_message, "content", None)).__name__
                        if debug_message is not None
                        else None
                    ),
                    "content_is_none": (
                        getattr(debug_message, "content", None) is None
                        if debug_message is not None
                        else None
                    ),
                    "finish_reason": (
                        getattr(debug_first, "finish_reason", None)
                        if debug_first is not None
                        else None
                    ),
                    "model": getattr(response, "model", None),
                },
                flush=True,
            )
        except Exception as debug_exc:
            print(
                "[LLM RESPONSE DEBUG ERROR]",
                repr(debug_exc),
                flush=True,
            )

        usage = getattr(response, "usage", None)
        t_in = getattr(usage, "prompt_tokens", 0) if usage else 0
        t_out = getattr(usage, "completion_tokens", 0) if usage else 0

        choices = getattr(response, "choices", None)
        if not choices:
            raise RuntimeError(
                f"LLM provider '{selected_name}' returned empty or null choices: {response}"
            )

        first_choice = choices[0]
        message = getattr(first_choice, "message", None)
        content = getattr(message, "content", None) if message is not None else None

        if content is None:
            raise RuntimeError(
                f"LLM provider '{selected_name}' returned null content in message: {response}"
            )

        return {
            "content": content,
            "model": response.model,
            "requested_model": selected_name,
            "finish_reason": getattr(first_choice, "finish_reason", None),
            "tokens_input": t_in,
            "tokens_output": t_out,
            "api_cost": self._calc_cost(t_in, t_out),
        }

    def _calc_cost(self, tokens_in: int, tokens_out: int) -> float:
        return round(
            (tokens_in * 0.14 + tokens_out * 0.28) / 1_000_000,
            6,
        )
