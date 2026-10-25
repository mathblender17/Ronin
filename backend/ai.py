import logging
import os
import random
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from . import ai_providers as providers
from .database import ROOT_DIR
from .schemas import DraftStory, ExpansionLayer, GeneratedConcept, InitialLayer, LeapCopy, LeapCopyLayer, QueryPlan

load_dotenv(ROOT_DIR / ".env")
logger = logging.getLogger("ronin.ai")


class AIServiceError(Exception):
    def __init__(self, message: str = "", *, output_invalid: bool = False, category: str | None = None, technical: str = ""):
        super().__init__(message)
        # True when the model answered but the layer was unusable. Only these failures get one layer-level retry.
        self.output_invalid = output_invalid
        # `message` is what the user sees. `category` and `technical` are for developer logs and diagnostics only.
        self.category = category
        self.technical = technical


class AIConfigurationError(AIServiceError):
    pass


@dataclass
class LayerResult:
    branches: list[GeneratedConcept]
    root_summary: str | None = None
    source_map: dict[str, list[dict[str, str]]] | None = None


def _client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise AIConfigurationError("Gemini is not configured. Add GEMINI_API_KEY to the project .env file and restart the API.")
    return genai.Client(api_key=api_key)


def _model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"


DEFAULT_PROVIDER_ORDER = "gemini,openrouter"
DEFAULT_OPENROUTER_PRIMARY = "nvidia/nemotron-3-super-120b-a12b:free"
DEFAULT_OPENROUTER_FALLBACKS = "google/gemma-4-26b-a4b-it:free,xingchen-agi/xing4.0-29b-a4b:free"
MAX_RETRY_AFTER_SECONDS = 10.0
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 8.0
LONG_COOLDOWN_SECONDS = 3600.0          # daily allowance used up, billing needed, or key rejected
RATE_LIMIT_COOLDOWN_SECONDS = 60.0      # per-minute limit: pause briefly, honouring Retry-After up to the maximum
RATE_LIMIT_COOLDOWN_MAX_SECONDS = 300.0
# Paid OpenAI-compatible APIs. They run only when named in RONIN_AI_PROVIDER_ORDER or passed as `only`.
OPENAI_COMPATIBLE: dict[str, tuple[str, str, str, str]] = {
    "deepseek": ("https://api.deepseek.com/chat/completions", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "deepseek-flash"),
    "kimi": ("https://api.moonshot.ai/v1/chat/completions", "MOONSHOT_API_KEY", "KIMI_MODEL", "kimi-k3.1-pro"),
}
NO_PROVIDER_MESSAGE = "No AI provider is configured. Add GEMINI_API_KEY or OPENROUTER_API_KEY to the project .env file and restart the API."

# What the user sees, keyed by failure category. Each message says what happened and what to do.
# Raw provider text never reaches these messages.
USER_MESSAGES = {
    providers.AUTH: "An AI provider rejected its API key. Check the key in your .env file, then restart Ronin.",
    providers.BILLING: "An AI provider needs billing set up before Ronin can use it. Ronin stopped, so nothing was charged.",
    providers.DAILY_QUOTA: "The free AI allowance for today is used up. Try again after it resets, or add another provider key in .env.",
    providers.RATE_LIMITED: "The AI services are busy right now. Wait about a minute, then try again. Your saved trails are safe.",
    providers.COOLDOWN: "The AI services are paused after a recent problem. Try again in a few minutes. Your saved trails are safe.",
    providers.INVALID_OUTPUT: "The AI returned an incomplete exploration layer. Please try again.",
    providers.BAD_REQUEST: "The AI services did not accept this request. Please try again shortly.",
    providers.POLICY: "The configured AI model is not on Ronin's approved list. Choose an approved model in .env.",
    providers.TIMEOUT: "The AI service took too long to respond. Please try again in a moment.",
    providers.CONNECTION: "Ronin could not reach the AI service. Check your connection and try again.",
    providers.UNAVAILABLE: "The AI service is temporarily unavailable. Please try again shortly.",
    "unconfigured": "No AI provider is set up yet. Add GEMINI_API_KEY or OPENROUTER_API_KEY to .env and restart Ronin.",
}
# When several providers failed, the message reflects the most actionable problem first.
USER_MESSAGE_PRIORITY = [
    providers.AUTH, providers.BILLING, providers.DAILY_QUOTA, providers.RATE_LIMITED, providers.COOLDOWN,
    providers.INVALID_OUTPUT, providers.POLICY, providers.BAD_REQUEST, providers.TIMEOUT,
    providers.CONNECTION, providers.UNAVAILABLE,
]

# Test seams: replaced in tests so retries and cooldowns run without real waiting.
_sleep = time.sleep
_clock = time.monotonic
_jitter = random.Random()
_state_lock = threading.Lock()
_cooldowns: dict[str, float] = {}
_last_success: dict[str, Any] | None = None
_recent_failures: deque[dict[str, str]] = deque(maxlen=10)
_local = threading.local()


@dataclass(frozen=True)
class AISettings:
    provider_order: tuple[str, ...]
    openrouter_models: tuple[str, ...]
    timeout: float
    max_retries: int
    max_output_tokens: int
    allow_paid: bool


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Ignoring %s: not a number. Using %s.", name, default)
        return default


def load_settings() -> AISettings:
    """Read the RONIN_AI_* settings on every call, so a restart is never needed to see a changed .env value."""
    order = tuple(item.strip().lower() for item in os.getenv("RONIN_AI_PROVIDER_ORDER", DEFAULT_PROVIDER_ORDER).split(",") if item.strip())
    primary = os.getenv("RONIN_AI_PRIMARY_MODEL", DEFAULT_OPENROUTER_PRIMARY).strip()
    fallbacks = [item.strip() for item in os.getenv("RONIN_AI_FALLBACK_MODELS", DEFAULT_OPENROUTER_FALLBACKS).split(",") if item.strip()]
    models = tuple(dict.fromkeys(item for item in [primary, *fallbacks] if item))
    return AISettings(
        provider_order=order,
        openrouter_models=models,
        timeout=_float_env("RONIN_AI_TIMEOUT_SECONDS", 45.0),
        max_retries=max(0, int(_float_env("RONIN_AI_MAX_RETRIES", 1))),
        max_output_tokens=max(256, int(_float_env("RONIN_AI_MAX_OUTPUT_TOKENS", 4096))),
        allow_paid=os.getenv("RONIN_AI_ALLOW_PAID_MODELS", "false").strip().lower() in {"1", "true", "yes"},
    )


def _openrouter_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise AIConfigurationError("OpenRouter is not configured. Add OPENROUTER_API_KEY to the project .env file to enable the fallback.")
    return key


def any_provider_configured() -> bool:
    keys = ["GEMINI_API_KEY", "OPENROUTER_API_KEY", *(key_env for _url, key_env, _m, _d in OPENAI_COMPATIBLE.values())]
    return any(os.getenv(key, "").strip() for key in keys)


def _compatible_key(provider: str) -> str:
    key_env = OPENAI_COMPATIBLE[provider][1]
    key = os.getenv(key_env, "").strip()
    if not key:
        raise AIConfigurationError(f"{provider.capitalize()} is not configured. Add {key_env} to the project .env file.")
    return key


def last_provider_model() -> str:
    provider, model = getattr(_local, "provider", None), getattr(_local, "model", None)
    return f"{provider}/{model}" if provider and model else ""


def _classify_gemini(exc: errors.APIError) -> providers.ProviderError:
    code = getattr(exc, "code", None)
    text = str(getattr(exc, "message", "") or exc).lower()
    if code == 429:
        if "per day" in text or "perday" in text or "daily" in text:
            return providers.ProviderError(providers.DAILY_QUOTA, "Gemini's daily quota is used up for now. Try again later.")
        return providers.ProviderError(providers.RATE_LIMITED, "Gemini rate limit or quota reached. Wait a little, then retry.")
    if code in (401, 403):
        return providers.ProviderError(providers.AUTH, "Gemini rejected the API key. Check GEMINI_API_KEY in the project .env file.")
    if code == 400:
        return providers.ProviderError(providers.BAD_REQUEST, "Gemini did not accept this request. Trying the next model.")
    if code in (408, 504):
        return providers.ProviderError(providers.TIMEOUT, "Gemini timed out. Retrying.")
    return providers.ProviderError(providers.UNAVAILABLE, "Gemini could not complete this request. Retrying.")


def _gemini_text(prompt: str, schema: type[BaseModel], model: str, settings: AISettings) -> str:
    client = _client()  # AIConfigurationError here means Gemini is not set up; the router skips it.
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.85,
                max_output_tokens=settings.max_output_tokens,
                http_options=types.HttpOptions(timeout=int(settings.timeout * 1000)),
            ),
        )
    except errors.APIError as exc:
        raise _classify_gemini(exc) from exc
    except Exception as exc:
        raise providers.ProviderError(providers.UNAVAILABLE, "The Gemini service is temporarily unavailable. Retrying.") from exc
    finally:
        client.close()
    text = response.text
    if not text:
        raise providers.ProviderError(providers.INVALID_OUTPUT, "Gemini returned an empty response. Trying the next model.")
    return text


def _enforce_policy(provider: str, model: str, settings: AISettings, explicit: bool = False) -> None:
    """Fail closed before any request is made. Paid models need RONIN_AI_ALLOW_PAID_MODELS and an explicit choice."""
    if provider in OPENAI_COMPATIBLE:
        return
    if provider == "gemini":
        if model in providers.GEMINI_MODELS or settings.allow_paid:
            return
        raise providers.ProviderError(providers.POLICY, f"Gemini model '{model}' is not on Ronin's approved list, so it was not called.")
    providers.approved_openrouter_model(model, allow_paid=settings.allow_paid, named_explicitly=explicit or model in settings.openrouter_models)


def _call(provider: str, model: str, prompt: str, schema: type[BaseModel], settings: AISettings) -> Any:
    try:
        if provider == "gemini":
            text = _gemini_text(prompt, schema, model, settings)
        elif provider in OPENAI_COMPATIBLE:
            text = providers.openrouter_generate_json(
                model=model, prompt=prompt, api_key=_compatible_key(provider), timeout=settings.timeout,
                max_tokens=settings.max_output_tokens, url=OPENAI_COMPATIBLE[provider][0],
            )
        else:
            text = providers.openrouter_generate_json(
                model=model, prompt=prompt, api_key=_openrouter_key(), timeout=settings.timeout, max_tokens=settings.max_output_tokens,
            )
    except (AIConfigurationError, providers.ProviderError):
        raise
    except Exception as exc:
        # An unexpected failure must not crash the chain or leak its message; it is treated as a retryable outage.
        raise providers.ProviderError(providers.UNAVAILABLE, "The AI service hit an unexpected error. Retrying.") from exc
    try:
        return schema.model_validate_json(text)
    except ValidationError as exc:
        message = (
            "Gemini returned an incomplete exploration layer. Please retry."
            if provider == "gemini"
            else "The model returned an incomplete exploration layer. Trying the next model."
        )
        raise providers.ProviderError(providers.INVALID_OUTPUT, message) from exc


def _model_key(provider: str, model: str) -> str:
    return f"{provider}:{model}"


def _cooling_down(provider: str) -> bool:
    with _state_lock:
        return _clock() < _cooldowns.get(provider, 0.0)


def _cooldown_seconds(error: providers.ProviderError) -> float:
    if error.category == providers.RATE_LIMITED:
        requested = error.retry_after if error.retry_after is not None else RATE_LIMIT_COOLDOWN_SECONDS
        return min(RATE_LIMIT_COOLDOWN_MAX_SECONDS, max(RATE_LIMIT_COOLDOWN_SECONDS, requested))
    return LONG_COOLDOWN_SECONDS


def _start_cooldown(provider: str, seconds: float) -> None:
    with _state_lock:
        _cooldowns[provider] = _clock() + seconds


def _record_success(provider: str, model: str, latency_ms: float) -> None:
    global _last_success
    with _state_lock:
        _last_success = {"provider": provider, "model": model, "latency_ms": round(latency_ms), "at": datetime.now(timezone.utc).isoformat()}
    logger.info("AI generation succeeded provider=%s model=%s latency_ms=%d", provider, model, round(latency_ms))


def _record_failure(provider: str, model: str, error: providers.ProviderError) -> None:
    with _state_lock:
        _recent_failures.append({"provider": provider, "model": model, "category": error.category, "at": datetime.now(timezone.utc).isoformat()})
    logger.warning("AI attempt failed provider=%s model=%s category=%s", provider, model, error.category)


def _retry_delay(error: providers.ProviderError, attempt: int) -> float | None:
    """Honour Retry-After when it is short. A long Retry-After means the next model is faster than waiting."""
    if error.retry_after is not None:
        return error.retry_after if error.retry_after <= MAX_RETRY_AFTER_SECONDS else None
    return min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** attempt)) * _jitter.uniform(0.5, 1.0)


def _structured_with_provider(prompt: str, schema: type[BaseModel], only: tuple[str, str] | None = None) -> tuple[Any, str]:
    """Try each configured provider and model in order, with bounded retries. Returns the validated layer and its provider.

    `only=(provider, model)` runs exactly that pair, for drafting with a chosen model or a model bake-off."""
    settings = load_settings()
    if only:
        settings = replace(settings, provider_order=(only[0],))
    failures: list[tuple[str, str, providers.ProviderError]] = []
    reached_provider = False
    for provider in settings.provider_order:
        if _cooling_down(provider):
            failures.append((provider, "-", providers.ProviderError(
                providers.COOLDOWN, f"{provider.capitalize()} is paused after a recent limit or billing response, so it was skipped.",
            )))
            continue
        if only:
            models = [only[1]]
        elif provider == "gemini":
            models = [_model()]
        elif provider in OPENAI_COMPATIBLE:
            _url, _key, model_env, default_model = OPENAI_COMPATIBLE[provider]
            models = [os.getenv(model_env, "").strip() or default_model]
        elif provider == "openrouter":
            models = list(settings.openrouter_models)
        else:
            logger.warning("Ignoring unknown AI provider in RONIN_AI_PROVIDER_ORDER: %s", provider)
            continue
        skip_provider = False
        for model in models:
            try:
                _enforce_policy(provider, model, settings, explicit=only is not None)
            except providers.ProviderError as error:
                failures.append((provider, model, error))
                _record_failure(provider, model, error)
                continue
            if _cooling_down(_model_key(provider, model)):
                failures.append((provider, model, providers.ProviderError(
                    providers.COOLDOWN, f"{model} is paused after a recent limit, so it was skipped.",
                )))
                continue
            for attempt in range(settings.max_retries + 1):
                started = _clock()
                try:
                    value = _call(provider, model, prompt, schema, settings)
                except AIConfigurationError:
                    skip_provider = True
                    break
                except providers.ProviderError as error:
                    reached_provider = True
                    failures.append((provider, model, error))
                    _record_failure(provider, model, error)
                    if error.category in providers.MODEL_COOLDOWN:
                        # A rate limit pauses this model only, and the next model is tried immediately with no retry.
                        _start_cooldown(_model_key(provider, model), _cooldown_seconds(error))
                        break
                    if error.category in providers.PROVIDER_COOLDOWN:
                        _start_cooldown(provider, _cooldown_seconds(error))
                        skip_provider = True
                        break
                    if error.retryable and attempt < settings.max_retries:
                        delay = _retry_delay(error, attempt)
                        if delay is not None:
                            _sleep(delay)
                            continue
                    break
                reached_provider = True
                _record_success(provider, model, (_clock() - started) * 1000)
                _local.provider = provider
                _local.model = model
                return value, provider
            if skip_provider:
                break

    raise _failure_error(failures, reached_provider)


def _failure_error(failures: list[tuple[str, str, providers.ProviderError]], reached_provider: bool) -> AIServiceError:
    """Build the one error the user sees. Developers get the provider, model and category trail in `technical`."""
    if not failures:
        return AIConfigurationError(USER_MESSAGES["unconfigured"], category="unconfigured", technical="no provider configured")
    categories = {error.category for _provider, _model_id, error in failures}
    chosen = next((category for category in USER_MESSAGE_PRIORITY if category in categories), providers.UNAVAILABLE)
    technical = "; ".join(f"{provider}/{model_id}: {error.category}" for provider, model_id, error in failures)
    if not reached_provider and chosen == providers.POLICY:
        return AIConfigurationError(USER_MESSAGES[chosen], category=chosen, technical=technical)
    return AIServiceError(
        USER_MESSAGES[chosen],
        output_invalid=chosen == providers.INVALID_OUTPUT,
        category=chosen,
        technical=technical,
    )


def _structured(prompt: str, schema: type[BaseModel], only: tuple[str, str] | None = None) -> Any:
    value, _provider = _structured_with_provider(prompt, schema, only)
    return value


def _source_map_for(question: str, concepts: list[GeneratedConcept]) -> dict[str, list[dict[str, str]]]:
    """Source grounding is a Gemini search feature. Layers from other providers carry no sources rather than unverified ones."""
    provider = getattr(_local, "provider", None)
    if provider not in (None, "gemini"):
        return {}
    return _grounded_sources(question, concepts)


def _is_layer_output_error(exc: AIServiceError) -> bool:
    return exc.output_invalid or "incomplete" in str(exc).lower()


def diagnostics() -> dict[str, Any]:
    """Safe status for the health endpoint: configuration flags, eligible model IDs, cooldowns and sanitized failures. No keys."""
    settings = load_settings()
    now = _clock()
    providers_status = []
    for provider in settings.provider_order:
        if provider == "gemini":
            configured = bool(os.getenv("GEMINI_API_KEY", "").strip())
            eligible = [_model()] if (_model() in providers.GEMINI_MODELS or settings.allow_paid) else []
        elif provider == "openrouter":
            configured = bool(os.getenv("OPENROUTER_API_KEY", "").strip())
            eligible = [item.model for item in providers.openrouter_eligibility(
                settings.openrouter_models, allow_paid=settings.allow_paid, explicit=frozenset(settings.openrouter_models),
            ) if item.eligible]
        else:
            continue
        with _state_lock:
            remaining = max(0.0, _cooldowns.get(provider, 0.0) - now)
        providers_status.append({
            "name": provider,
            "configured": configured,
            "eligible_models": eligible,
            "cooldown_seconds_remaining": round(remaining),
        })
    with _state_lock:
        last_success = dict(_last_success) if _last_success else None
        recent_failures = list(_recent_failures)
        model_cooldowns = [
            {"model": key.split(":", 1)[1], "provider": key.split(":", 1)[0], "seconds_remaining": round(until - now)}
            for key, until in _cooldowns.items() if ":" in key and until > now
        ]
    return {
        "providers": providers_status,
        "model_cooldowns": model_cooldowns,
        "paid_models_allowed": settings.allow_paid,
        "last_success": last_success,
        "recent_failures": recent_failures,
    }


def _words(value: str) -> set[str]:
    return {part for part in re.findall(r"[a-z0-9]+", value.lower()) if len(part) > 2}


def title_key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def unique_concepts(concepts: list[GeneratedConcept], existing_titles: list[str]) -> list[GeneratedConcept]:
    kept: list[GeneratedConcept] = []
    seen = [title_key(title) for title in existing_titles]
    for concept in concepts:
        key = title_key(concept.title)
        if not key or any(
            key == other or SequenceMatcher(None, key, other).ratio() >= 0.9
            or (len(_words(key)) > 1 and len(_words(other)) > 1 and len(_words(key) & _words(other)) / len(_words(key) | _words(other)) >= 0.88)
            for other in seen
        ):
            continue
        kept.append(concept)
        seen.append(key)
    return kept


def _grounded_sources(question: str, concepts: list[GeneratedConcept]) -> dict[str, list[dict[str, str]]]:
    if not concepts:
        return {}
    prompt = (
        "Find real, useful web sources for the following exploration concepts. Search the web. "
        "Write one short, factual sentence under an exact heading for each concept, and rely on the search results. "
        "Do not invent source links. If a concept has no good source, say so under its heading.\n\n"
        f"Starting question: {question}\n"
        + "\n".join(f"## {item.title}\nContext: {item.summary}" for item in concepts)
    )
    try:
        client = _client()
        try:
            response = client.models.generate_content(
                model=_model(),
                contents=prompt,
                config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
            )
        finally:
            client.close()
    except Exception:
        # Source search is optional. An honest empty list is preferable to unverified links.
        return {}

    try:
        candidate = (response.candidates or [])[0]
        metadata = getattr(candidate, "grounding_metadata", None)
        chunks = list(getattr(metadata, "grounding_chunks", None) or [])
        supports = list(getattr(metadata, "grounding_supports", None) or [])
    except (AttributeError, IndexError, TypeError):
        return {}

    output: dict[str, list[dict[str, str]]] = {title_key(item.title): [] for item in concepts}
    by_key = {title_key(item.title): item for item in concepts}
    for support in supports:
        segment = getattr(support, "segment", None)
        cited_text = str(getattr(segment, "text", "") or "")
        # The prompt asks for one "## Title" heading per concept. When the cited segment carries that
        # heading, it identifies the concept exactly; word overlap is only the fallback.
        heading = re.match(r"\s*#+\s*(.+)", cited_text)
        best: tuple[GeneratedConcept, float] | None = None
        if heading and title_key(heading.group(1)) in by_key:
            best = (by_key[title_key(heading.group(1))], 1.0)
        else:
            cited_words = _words(cited_text)
            for concept in concepts:
                concept_words = _words(f"{concept.title} {concept.summary}")
                score = len(cited_words & concept_words) / max(1, len(cited_words | concept_words))
                if best is None or score > best[1]:
                    best = (concept, score)
        # Attach a citation only when its cited text has a meaningful relationship to one node.
        if not best or best[1] < 0.12:
            continue
        cited_text = re.sub(r"^\s*#+[^\n]*\n?", "", cited_text).strip()
        for chunk_index in getattr(support, "grounding_chunk_indices", None) or []:
            if chunk_index >= len(chunks):
                continue
            web = getattr(chunks[chunk_index], "web", None)
            url = str(getattr(web, "uri", "") or "")
            title = str(getattr(web, "title", "") or "")
            if not url.startswith(("https://", "http://")) or not title:
                continue
            bucket = output[title_key(best[0].title)]
            if not any(source["url"] == url for source in bucket):
                host = url.split("//", 1)[-1].split("/", 1)[0]
                # Grounding links are Google redirect URLs; the chunk title carries the real site domain.
                publisher = re.sub(r"^www\.", "", title if host.endswith("vertexaisearch.cloud.google.com") else host)
                bucket.append({"title": title[:300], "url": url[:2000], "publisher": publisher[:200], "citation_text": cited_text[:1000]})
    return {key: sources[:3] for key, sources in output.items()}


def generate_initial(question: str) -> LayerResult:
    prompt = f"""You are Ronin, a curiosity engine. You do not write reports; you open doors. Give the user five genuinely different ways into this question, each one something a curious person would want to click.
Starting question: {question}

Return exactly five branches, and make them different KINDS of doors, not five topics from one syllabus. Draw from a mix such as:
- a hidden mechanism or incentive that drives the phenomenon;
- a concrete historical or real-world case where it played out;
- a lens from an unexpected discipline (biology, economics, game theory, psychology, design…);
- a tension or trade-off at the heart of the question;
- a challenge to the question's own premise or a common assumption inside it.

Titles: 2–7 words, specific and intriguing, the way a good essay or chapter title hooks a reader. Avoid broad category labels such as "Economic Factors", "Historical Context", or "Decline in X".
Summary: one or two sentences that give the most interesting claim, tension, or fact, not a definition. Make the reader want the next layer.
Connection reason: one sentence on exactly how this door connects to the starting question.
Exploration question: a sharp, specific question that the next layer could answer.
Domain: the single most relevant field, in one or two words.

Write plainly and vividly. Never open with stock phrases such as "This branch explores" or "This concept examines". Keep everything short; the detail panel, not the card, carries context. Only state facts you are confident are accurate; prefer framing a contested point as a question.

Root summary: two or three sentences that frame why the question is interesting and genuinely open. Do not restate the question or open with "The question … explores"; start with the substance. If the question has common meanings that would materially change the map, name the interpretation you chose and the main alternative so the user can redirect. Do not include sources or URLs."""

    last_error: AIServiceError | None = None
    for attempt in range(2):
        try:
            _local.provider = None
            result: InitialLayer = _structured(prompt, InitialLayer)
        except AIServiceError as exc:
            # Only an unusable layer earns a second attempt. A provider outage already had the full fallback chain.
            if isinstance(exc, AIConfigurationError) or not _is_layer_output_error(exc) or attempt == 1:
                raise
            last_error = exc
            prompt += "\nRetry instruction: the previous response did not validate. Return a complete root summary and exactly five fully populated branches."
            continue

        branches = unique_concepts(result.branches, [question])
        if len(branches) == 5:
            branches = branches[:5]
            return LayerResult(branches, result.root_summary, _source_map_for(question, branches))

        last_error = AIServiceError(
            f"The AI returned {len(branches)} distinct first-level branches after duplicate filtering; Ronin needs exactly 5."
        )
        if attempt == 0:
            duplicate_titles = ", ".join(item.title for item in result.branches if item not in branches)
            prompt += (
                "\nRetry instruction: exactly five unique concepts are required. Replace any duplicate or near-duplicate ideas"
                f" and keep every direction distinct. Concepts rejected as duplicates: {duplicate_titles or 'none'}."
            )

    raise last_error or AIServiceError("Ronin could not generate five distinct first-level branches. Please retry.")


def generate_expansion(
    question: str,
    selected: GeneratedConcept,
    ancestors: list[str],
    graph_context: list[str],
    direction: str | None = None,
) -> LayerResult:
    prompt = f"""You are Ronin, a curiosity engine, not a report writer. Continue a persistent concept graph with a short, compelling next layer that goes deeper, not wider.
Original question: {question}
Path from root: {' → '.join(ancestors)}
Selected concept: {selected.title}
Selected concept summary: {selected.summary}
Connection to parent: {selected.connection_reason}
User's optional follow-up direction: {direction or '(none — suggest surprising but relevant directions)'}
Existing titles in this exploration (avoid duplicates and simple rewordings): {', '.join(graph_context[:100])}

Return 3 to 5 genuinely distinct child concepts that each go one step more specific than the selected concept: a named mechanism, a concrete case, a surprising consequence, a competing explanation, or an unresolved question. Mix these kinds rather than giving several of the same kind, and let at least one child cross into a different discipline when it fits.

Titles: 2–7 words, specific and intriguing, never a broad category label. Summary: one or two sentences carrying the most interesting claim or tension, not a definition. Connection reason: one sentence on the concrete relationship to "{selected.title}". Exploration question: a sharp question for the next layer. Domain: one or two words.

Follow the user's direction when one is given, while keeping every child attached to the selected concept. Write plainly and vividly, never open with stock phrases such as "This concept explores", and do not repeat or reword any existing graph title. Only state facts you are confident are accurate. Do not invent sources or URLs."""
    _local.provider = None
    result: ExpansionLayer = _structured(prompt, ExpansionLayer)
    branches = unique_concepts(result.branches, graph_context + [selected.title])
    if len(branches) < 3:
        raise AIServiceError("The AI suggested too few new directions. Try a more specific follow-up or retry.")
    return LayerResult(branches[:5], source_map=_source_map_for(question, branches[:5]))


EMBEDDING_MODEL = "gemini-embedding-001"


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Gemini embeddings for leap scoring. Any failure becomes AIServiceError so callers can fall back to an unranked leap."""
    client = _client()
    try:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 100):
            response = client.models.embed_content(
                model=EMBEDDING_MODEL, contents=texts[start:start + 100],
                config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY"),
            )
            vectors += [list(item.values) for item in response.embeddings]
    except Exception as exc:
        raise AIServiceError("Ronin could not compare the concepts in this trail right now.", technical=str(exc)) from exc
    finally:
        client.close()
    return vectors


def clean_waypoints(proposed: list[str], interior: list[str]) -> list[str]:
    """Keep only titles that really sit inside the path, so a card never shows an invented step."""
    real = {" ".join(title.split()): title for title in interior}
    kept = [real[key] for title in proposed if (key := " ".join(title.split())) in real]
    kept = list(dict.fromkeys(kept))[:3]
    return kept or [interior[len(interior) // 2]]


def generate_leap_copy(question: str, paths: list[list[tuple[str, str]]]) -> list[LeapCopy]:
    """Write a hook and a reframing line for each root → node path. Each path is (title, connection_reason), root first."""
    blocks = "\n\n".join(
        f"Path {index}:\n" + "\n".join(f"- {title} (link to previous: {reason})" for title, reason in path)
        for index, path in enumerate(paths)
    )
    prompt = f"""You are Ronin. A person started with the question "{question}" and followed each path below, one step at a time, to its last title.

For each path, write:
- hook: at most 12 words. The "wait, what?" line about how the first title led to the last. Name both ends concretely.
- reframe: at most 25 words. Why the leap makes sense once you see the steps. Phrase it as an interpretation, not a proven fact.
- waypoints: two or three titles copied exactly from that path's middle steps (not the first or last title).

Use only the titles and links given. Do not invent facts, people, dates, or sources.

{blocks}

Return JSON only, in this shape, with one entry per path and its index:
{{"leaps": [{{"index": 0, "hook": "...", "reframe": "...", "waypoints": ["..."]}}]}}"""
    _local.provider = None
    result: LeapCopyLayer = _structured(prompt, LeapCopyLayer)
    leaps = []
    for leap in result.leaps:
        if 0 <= leap.index < len(paths):
            interior = [title for title, _reason in paths[leap.index][1:-1]]
            leaps.append(leap.model_copy(update={"waypoints": clean_waypoints(leap.waypoints, interior)}))
    return leaps


DRAFT_PROMPT_VERSION = "draft-v1"
EDITORIAL_BAR = """Ronin publishes rabbit holes for people who love being intellectually lost: lost media, dead websites, meme origins, \
old forums, Japanese internet subculture, uncanny history. The goal is intrigue, not education: make the familiar feel unfamiliar.
- Every discovery must change what the reader thought they knew, or open a sharper question. No listicle filler.
- Never manufacture mystery or suspense the evidence does not support. The reality should be strange enough.
- Investigate conspiracies, never invent them. Keep facts, attributed claims, interpretation and speculation apart.
- An anonymous anecdote (for example from Reddit) is at most a claim, never a fact."""


def plan_queries(seed: str, only: tuple[str, str] | None = None) -> QueryPlan:
    prompt = f"""You are Ronin's research planner. {EDITORIAL_BAR}

Seed idea: {seed}

Write 4 to 8 search queries that would surface real primary material about this seed: original posts, archived pages, \
first-hand accounts, videos, forum threads. Give each query one angle: origin (where it started), stranger (the odd detail), \
counterpoint (evidence against the obvious story), old-web (archived or forgotten sites), japanese (Japanese-language sources, \
written in Japanese). Use the japanese angle only when it fits the seed.

Return JSON only, in this shape:
{{"queries": [{{"text": "...", "angle": "origin"}}]}}"""
    _local.provider = None
    return _structured(prompt, QueryPlan, only)


def write_draft(seed: str, finds: list[dict], only: tuple[str, str] | None = None) -> DraftStory:
    numbered = "\n".join(
        f"[{number}] {f['medium']} · {f['title']} · {f.get('creator') or '-'} · {f.get('date') or '-'} · {f['url']} · {f.get('snippet') or ''}"
        for number, f in enumerate(finds, start=1)
    )
    prompt = f"""You are Ronin's story drafter. {EDITORIAL_BAR}

Seed idea: {seed}

Numbered finds from research (the only material you may cite):
{numbered or '(no finds: mark every discovery as speculation or open)'}

Draft one rabbit hole in five beats:
- title: the story's name. hook: one impossible-looking question.
- entry: the specific artifact, clue or event where the trail starts.
- descent: 1 to 6 discoveries, each changing the question.
- leap: the unexpected connection between two seemingly unrelated worlds; its why is the one-line reframe.
- known: what is established. open: what remains unresolved.
Each discovery has: title, evidence (fact | claim | interpretation | speculation | open), why (how it follows from the \
previous step), body (2-4 vivid sentences), sources (find numbers only, never URLs). A fact or claim must cite at least one find.

Return JSON only, in this shape:
{{"title": "...", "hook": "...", "entry": {{"title": "...", "evidence": "fact", "why": "...", "body": "...", "sources": [1]}}, \
"descent": [{{...same shape...}}], "leap": {{...same shape...}}, "known": "...", "open": "..."}}"""
    _local.provider = None
    return _structured(prompt, DraftStory, only)
