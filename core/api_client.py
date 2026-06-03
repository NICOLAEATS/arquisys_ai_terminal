"""
Cliente único que habla con la API OpenCode Zen.
Reemplaza directamente al cliente que usa openai SDK apuntado al endpoint Zen.
"""
import re

from openai import OpenAI
from config import (
    OPENCODE_API_KEY,
    OPENCODE_BASE_URL,
    AVAILABLE_MODELS,
    FREE_MODEL_MARKERS,
)


def _extract_model_id(item) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("id") or "")
    return str(getattr(item, "id", "") or "")


def _is_free_model(model_id: str) -> bool:
    text = model_id.lower()
    return any(marker in text for marker in FREE_MODEL_MARKERS)


def _alias_for_model(model_id: str, used: set[str]) -> str:
    base = model_id.lower()
    for suffix in ("-free", ":free", "_free", ".free"):
        base = base.replace(suffix, "")

    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-") or "model"
    alias = base.split("-")[0] or base

    if alias in {"openrouter", "opencode", "free"} and "-" in base:
        alias = base.split("-", 1)[1].split("-")[0]

    candidate = alias
    idx = 2
    while candidate in used:
        candidate = f"{alias}{idx}"
        idx += 1
    used.add(candidate)
    return candidate


def build_model_registry(model_ids: list[str]) -> dict[str, str]:
    used: set[str] = set()
    registry: dict[str, str] = {}

    for model_id in sorted(set(model_ids)):
        if not model_id or not _is_free_model(model_id):
            continue
        alias = _alias_for_model(model_id, used)
        registry[alias] = model_id

    if registry:
        default = (
            registry.get("minimax")
            or registry.get("hy3")
            or registry.get("nemotron")
            or next(iter(registry.values()))
        )
        registry["default"] = default
    return registry


class OpenCodeClient:
    """Wrapper sobre la SDK de OpenAI apuntado a OpenCode Zen."""

    def __init__(self, model_key: str = "default"):
        self.api_key = OPENCODE_API_KEY
        self.base_url = OPENCODE_BASE_URL
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=30.0,
        )
        self.models = dict(AVAILABLE_MODELS)
        self.model = self.models.get(model_key, self.models["default"])

    def configure(self, api_key: str | None = None, base_url: str | None = None):
        if api_key is not None:
            self.api_key = api_key
        if base_url is not None:
            self.base_url = base_url
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=30.0,
        )

    def refresh_free_models(self) -> dict[str, str]:
        """Consulta OpenCode Zen y devuelve modelos gratuitos disponibles ahora."""
        try:
            response = self.client.models.list()
            items = getattr(response, "data", response)
            model_ids = [_extract_model_id(item) for item in items]
            registry = build_model_registry(model_ids)
            if registry:
                self.models = registry
                if self.model not in registry.values():
                    self.model = registry["default"]
                return registry
        except Exception:
            pass

        self.models = dict(AVAILABLE_MODELS)
        if self.model not in self.models.values():
            self.model = self.models["default"]
        return self.models

    # ── Llamada base ────────────────────────────────────────────────
    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2000,
        stream: bool = False,
    ):
        """Realiza una llamada chat. Si stream=True retorna el generador."""
        kwargs = dict(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
        )
        return self.client.chat.completions.create(**kwargs)

    def chat_text(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> str:
        """Llamada sin streaming — devuelve el texto directamente."""
        resp = self.chat(messages, temperature=temperature,
                         max_tokens=max_tokens, stream=False)
        return resp.choices[0].message.content or ""

    def switch_model(self, model_key: str, models: dict[str, str] | None = None):
        registry = models or self.models or AVAILABLE_MODELS
        if model_key in registry:
            self.model = registry[model_key]
        elif model_key in registry.values():
            self.model = model_key
        else:
            self.model = registry.get("default", AVAILABLE_MODELS["default"])
