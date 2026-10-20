"""Provider-level pieces of Ronin's AI layer: the free-model policy, the OpenRouter adapter, and error classification.

Adapters turn provider responses into ProviderError categories. Business logic in ai.py never sees SDK or HTTP objects,
and no message produced here contains an API key.
"""

import json
from dataclasses import dataclass

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Free OpenRouter variants whose /api/v1/models entry advertises JSON response_format (checked 2026-10-20).
# Listing here is necessary but not sufficient: the ID must also end in ":free", and the entry must be re-checked
# when OpenRouter changes its catalogue. Nemotron 3 Ultra's free variant is excluded because it does not advertise
# JSON output, and openrouter/free is excluded because it has no ":free" suffix and may route to paid models.
FREE_OPENROUTER_MODELS = frozenset({
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-26b-a4b-it:free",
    "xingchen-agi/xing4.0-29b-a4b:free",
    "dots-studio/dots-3-note-preview:free",
})
# Gemini models Ronin has been run against. Free-tier eligibility depends on the account and cannot be checked from code.
GEMINI_MODELS = frozenset({"gemini-2.5-flash", "gemini-2.5-flash-lite"})

# Categories. Only these reach logs and health diagnostics, never raw provider text.
RATE_LIMITED = "rate_limited"       # per-minute or burst limit: retry after a short wait
DAILY_QUOTA = "daily_quota"         # daily allowance used up: do not retry, skip the provider for a while
BILLING = "billing"                 # needs credits: never auto-spend, skip the provider
AUTH = "auth"                       # key rejected: skip the provider, tell the user to check the key
BAD_REQUEST = "bad_request"         # this model or request shape is rejected: skip the model
INVALID_OUTPUT = "invalid_output"   # malformed or schema-invalid output: skip the model
POLICY = "policy"                   # model is not on the approved list: skip the model
COOLDOWN = "cooldown"               # provider paused after a daily, billing or auth failure: skipped without a request
UNAVAILABLE = "unavailable"         # upstream 5xx or unexpected failure: retry with backoff
TIMEOUT = "timeout"                 # request exceeded the timeout: retry with backoff
CONNECTION = "connection"           # network failure: retry with backoff

# A rate limit is never retried. Retrying into a limit only spends more of the quota, so that model is paused briefly
# and the next eligible model or provider is tried at once. A daily allowance, billing or a rejected key pauses the whole provider.
RETRYABLE = frozenset({UNAVAILABLE, TIMEOUT, CONNECTION})
MODEL_COOLDOWN = frozenset({RATE_LIMITED})
PROVIDER_COOLDOWN = frozenset({DAILY_QUOTA, BILLING, AUTH})


class ProviderError(Exception):
    """A sanitized, classified failure from one provider call. `message` is safe to show to a user."""

    def __init__(self, category: str, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.category = category
        self.message = message
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.category in RETRYABLE


def approved_openrouter_model(model: str, *, allow_paid: bool, named_explicitly: bool) -> str:
    """Return the model ID if policy allows it, or raise ProviderError(POLICY) before any request is made.

    Free models must be on the allowlist and end in ':free'. A paid model is only accepted when the operator enabled
    RONIN_AI_ALLOW_PAID_MODELS and named that exact model in RONIN_AI_PRIMARY_MODEL or RONIN_AI_FALLBACK_MODELS.
    Paid models are never chosen automatically.
    """
    if model in FREE_OPENROUTER_MODELS and model.endswith(":free"):
        return model
    if allow_paid and named_explicitly and not model.endswith(":free"):
        return model
    raise ProviderError(
        POLICY,
        f"OpenRouter model '{model}' is not on Ronin's approved free list, so it was not called. "
        "Add it to the approved list in backend/ai_providers.py, or enable paid models deliberately.",
    )


def parse_retry_after(value: str | None) -> float | None:
    """Retry-After as seconds. HTTP-date values are ignored, so the caller falls back to its own backoff."""
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _error_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500].lower()
    error = payload.get("error", payload) if isinstance(payload, dict) else payload
    if isinstance(error, dict):
        return json.dumps(error, ensure_ascii=False)[:1000].lower()
    return str(error)[:500].lower()


def classify_openrouter(status: int, body_text: str, retry_after: str | None) -> ProviderError:
    """Map an OpenRouter HTTP error to a category. Upstream-provider failures can be retried; daily free limits cannot."""
    after = parse_retry_after(retry_after)
    if status in (401, 403):
        return ProviderError(AUTH, "OpenRouter rejected the API key. Check OPENROUTER_API_KEY in the project .env file.")
    if status == 402 or ("insufficient" in body_text and "credit" in body_text):
        return ProviderError(BILLING, "OpenRouter needs credits for this request, and Ronin only uses free models. Nothing was charged.")
    if status == 429:
        if "per-day" in body_text or "per day" in body_text or "daily" in body_text or "free-models-per-day" in body_text:
            return ProviderError(DAILY_QUOTA, "OpenRouter's free daily allowance is used up for now. Try again later.")
        return ProviderError(RATE_LIMITED, "OpenRouter rate limit reached. Wait a little, then retry.", retry_after=after)
    if status in (400, 404, 422):
        return ProviderError(BAD_REQUEST, "OpenRouter did not accept this model or request. Trying the next approved model.")
    if status in (408, 504):
        return ProviderError(TIMEOUT, "OpenRouter timed out. Retrying.", retry_after=after)
    return ProviderError(UNAVAILABLE, "OpenRouter is temporarily unavailable. Retrying.", retry_after=after)


def openrouter_generate_json(
    *,
    model: str,
    prompt: str,
    api_key: str,
    timeout: float,
    max_tokens: int,
    temperature: float = 0.85,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Ask OpenRouter for one JSON object. Returns the raw message content, which the caller validates with Pydantic."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {api_key}", "X-Title": "Ronin"}
    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            response = client.post(OPENROUTER_URL, headers=headers, json=body)
    except httpx.TimeoutException as exc:
        raise ProviderError(TIMEOUT, "OpenRouter timed out. Retrying.") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(CONNECTION, "Could not reach OpenRouter. Retrying.") from exc

    if response.status_code >= 400:
        raise classify_openrouter(response.status_code, _error_text(response), response.headers.get("retry-after"))
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ProviderError(INVALID_OUTPUT, "OpenRouter returned an unreadable response. Trying the next approved model.") from exc
    if not isinstance(content, str) or not content.strip():
        raise ProviderError(INVALID_OUTPUT, "OpenRouter returned an empty response. Trying the next approved model.")
    return content


@dataclass(frozen=True)
class ModelStatus:
    provider: str
    model: str
    eligible: bool


def openrouter_eligibility(models: tuple[str, ...], *, allow_paid: bool, explicit: frozenset[str]) -> list[ModelStatus]:
    """Which configured OpenRouter models pass policy, for diagnostics. Makes no network call."""
    statuses = []
    for model in models:
        try:
            approved_openrouter_model(model, allow_paid=allow_paid, named_explicitly=model in explicit)
            statuses.append(ModelStatus("openrouter", model, True))
        except ProviderError:
            statuses.append(ModelStatus("openrouter", model, False))
    return statuses
