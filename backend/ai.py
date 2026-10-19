import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from .database import ROOT_DIR
from .schemas import ExpansionLayer, GeneratedConcept, InitialLayer

load_dotenv(ROOT_DIR / ".env")


class AIServiceError(Exception):
    pass


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


def _structured(prompt: str, schema: type[InitialLayer] | type[ExpansionLayer]) -> Any:
    try:
        client = _client()
        try:
            response = client.models.generate_content(
                model=_model(),
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.85,
                ),
            )
        finally:
            client.close()
        text = response.text
        if not text:
            raise AIServiceError("Gemini returned an empty response. Try again.")
        return schema.model_validate_json(text)
    except AIServiceError:
        raise
    except ValidationError as exc:
        raise AIServiceError("Gemini returned an incomplete exploration layer. Please retry.") from exc
    except errors.APIError as exc:
        code = getattr(exc, "code", None)
        if code == 429:
            raise AIServiceError("Gemini rate limit or quota reached. Wait a little, then retry.") from exc
        raise AIServiceError("Gemini could not complete this request. Check your API access and try again.") from exc
    except Exception as exc:
        raise AIServiceError("The AI service is temporarily unavailable. Try again in a moment.") from exc


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
            result: InitialLayer = _structured(prompt, InitialLayer)
        except AIServiceError as exc:
            if isinstance(exc, AIConfigurationError) or "rate limit" in str(exc).lower() or attempt == 1:
                raise
            last_error = exc
            prompt += "\nRetry instruction: the previous response did not validate. Return a complete root summary and exactly five fully populated branches."
            continue

        branches = unique_concepts(result.branches, [question])
        if len(branches) == 5:
            branches = branches[:5]
            return LayerResult(branches, result.root_summary, _grounded_sources(question, branches))

        last_error = AIServiceError(
            f"Gemini returned {len(branches)} distinct first-level branches after duplicate filtering; Ronin needs exactly 5."
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
    result: ExpansionLayer = _structured(prompt, ExpansionLayer)
    branches = unique_concepts(result.branches, graph_context + [selected.title])
    if len(branches) < 3:
        raise AIServiceError("Gemini suggested too few new directions. Try a more specific follow-up or retry.")
    return LayerResult(branches[:5], source_map=_grounded_sources(question, branches[:5]))
