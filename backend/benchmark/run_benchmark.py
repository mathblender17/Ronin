"""Opt-in model comparison. It spends free-model quota, so it refuses to run unless RONIN_LIVE_BENCHMARK=1.

It calls Ronin's production generation functions with one model, no fallback and no retries, so every failure is visible.
Prompts, validation, and de-duplication are the application's own code. Only the model choice changes.

Usage:
  RONIN_LIVE_BENCHMARK=1 python -m backend.benchmark.run_benchmark --model nvidia/nemotron-3-super-120b-a12b:free --out results.json
"""

import argparse
import json
import os
import time
from pathlib import Path

from backend import ai, ai_providers as providers
from backend.schemas import GeneratedConcept

FIXTURES = Path(__file__).with_name("fixtures.json")


def run_case(case: dict) -> dict:
    started = time.monotonic()
    titles: list[str] = []
    error = None
    try:
        if case["kind"] == "initial":
            layer = ai.generate_initial(case["question"])
            titles = [item.title for item in layer.branches]
            ok = len(titles) == 5
        else:
            selected = GeneratedConcept(
                title=case["selected_title"],
                summary=case["selected_summary"],
                connection_reason=case["selected_connection"],
                exploration_question="What would a curious reader ask next?",
                domain="Psychology",
            )
            layer = ai.generate_expansion(case["question"], selected, case["ancestors"], case["graph_context"])
            titles = [item.title for item in layer.branches]
            ok = 3 <= len(titles) <= 5
    except ai.AIServiceError as exc:
        ok = False
        error = f"{type(exc).__name__}: {exc}"
    distinct = len({ai.title_key(title) for title in titles})
    return {
        "case": case["id"],
        "schema_valid": ok,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "titles": titles,
        "distinct_titles": distinct,
        "duplicate_titles": len(titles) - distinct,
        "error": error,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare one OpenRouter model on Ronin's fixtures.")
    parser.add_argument("--model", required=True, help="An approved free model ID, for example nvidia/nemotron-3-super-120b-a12b:free")
    parser.add_argument("--out", required=True, help="Where to write the JSON results")
    parser.add_argument("--case", action="append", help="Run only these case IDs (repeatable)")
    args = parser.parse_args()

    if os.getenv("RONIN_LIVE_BENCHMARK") != "1":
        raise SystemExit("Refusing to run: set RONIN_LIVE_BENCHMARK=1 to spend free-model quota deliberately.")
    if not os.getenv("OPENROUTER_API_KEY"):
        raise SystemExit("Refusing to run: OPENROUTER_API_KEY is not set.")
    try:
        providers.approved_openrouter_model(args.model, allow_paid=False, named_explicitly=True)
    except providers.ProviderError as error:
        raise SystemExit(f"Refusing to run: {error}")

    # One model, no fallback, no retries, so each result reflects that model alone.
    os.environ["RONIN_AI_PROVIDER_ORDER"] = "openrouter"
    os.environ["RONIN_AI_PRIMARY_MODEL"] = args.model
    os.environ["RONIN_AI_FALLBACK_MODELS"] = ""
    os.environ["RONIN_AI_MAX_RETRIES"] = "0"
    os.environ["RONIN_AI_ALLOW_PAID_MODELS"] = "false"

    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    cases = [case for case in fixtures["cases"] if not args.case or case["id"] in args.case]
    results = [run_case(case) for case in cases]
    summary = {
        "model": args.model,
        "cases": len(results),
        "schema_valid": sum(1 for item in results if item["schema_valid"]),
        "results": results,
    }
    Path(args.out).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{args.model}: {summary['schema_valid']}/{summary['cases']} cases schema-valid. Wrote {args.out}")


if __name__ == "__main__":
    main()
