"""THROWAWAY SPIKE: find rabbit holes in your own AI conversations.

Question it answers: does "each step close to the last, end far from the start" pick out real rabbit holes,
and do the stories it writes make you say "huh, that's me"?

Usage:
  python spike/drift.py claude [~/.claude/projects]      # Claude Code transcripts
  python spike/drift.py chatgpt path/to/conversations.json # ChatGPT export
Writes spike/out/report.md. Message text is sent to Gemini (embeddings + stories) with your own key.
"""
import hashlib
import json
import math
import os
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
load_dotenv(ROOT.parent / ".env")

NOISE = ("<command-", "<task-notification", "<system-reminder", "<local-command", "Base directory for this skill",
         "[Image", "Caveat:", "[Request interrupted")


def clean(text: str) -> str | None:
    text = text.strip()
    if not text or text.startswith(NOISE):
        return None
    text = re.sub(r"</?pasted_content[^>]*>", "", text)
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S)
    text = " ".join(text.split())
    return text[:1500] if len(text) >= 12 else None


def load_claude(root: Path) -> list[dict]:
    sessions = []
    for f in root.glob("*/*.jsonl"):  # top-level sessions only; subagent transcripts are not the user's thinking
        msgs = []
        for line in f.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "user" or d.get("isMeta"):
                continue
            c = d.get("message", {}).get("content")
            parts = [c] if isinstance(c, str) else [p.get("text", "") for p in c or [] if isinstance(p, dict) and p.get("type") == "text"]
            for p in parts:
                if (t := clean(p)):
                    msgs.append((d["timestamp"], t))
        if len(msgs) >= 2:
            project = f.parent.name.split("-Desktop-")[-1][-30:]
            sessions.append({"id": f.stem[:8], "title": project, "messages": sorted(msgs)})
    return sessions


def load_chatgpt(path: Path) -> list[dict]:
    sessions = []
    for conv in json.loads(path.read_text(encoding="utf-8")):
        mapping, node, msgs = conv.get("mapping", {}), conv.get("current_node"), []
        while node:  # walk the branch the user ended on, back to the root
            m = (mapping.get(node) or {}).get("message") or {}
            if m.get("author", {}).get("role") == "user":
                parts = [p for p in (m.get("content", {}).get("parts") or []) if isinstance(p, str)]
                if (t := clean(" ".join(parts))):
                    ts = datetime.fromtimestamp(m.get("create_time") or conv.get("create_time") or 0, timezone.utc).isoformat()
                    msgs.append((ts, t))
            node = (mapping.get(node) or {}).get("parent")
        if len(msgs) >= 2:
            sessions.append({"id": conv.get("id", "")[:8], "title": conv.get("title") or "untitled", "messages": sorted(msgs)})
    return sessions


def embed(client: genai.Client, texts: list[str]) -> list[list[float]]:
    cache_file = OUT / "embed_cache.json"
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    key = lambda t: hashlib.sha1(t.encode()).hexdigest()
    todo = list(dict.fromkeys(t for t in texts if key(t) not in cache))
    for i in range(0, len(todo), 50):
        batch = todo[i:i + 50]
        res = client.models.embed_content(
            model="gemini-embedding-001", contents=batch,
            config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY", output_dimensionality=768),
        )
        for t, e in zip(batch, res.embeddings):
            cache[key(t)] = e.values
        cache_file.write_text(json.dumps(cache))
    return [cache[key(t)] for t in texts]


def cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def analyse(msgs, vecs, far):
    """Drift step = first message that is 'far' from where the chain started. Smoothness = mean neighbour similarity."""
    to_start = [cos(vecs[0], v) for v in vecs]
    neighbour = [cos(vecs[i], vecs[i + 1]) for i in range(len(vecs) - 1)]
    drift = next((i for i, s in enumerate(to_start) if s < far), None)
    return {
        "steps": len(msgs), "drift_step": drift, "end_distance": round(1 - to_start[-1], 3),
        "smoothness": round(statistics.mean(neighbour), 3), "to_start": [round(s, 2) for s in to_start],
        "biggest_jump": max(range(len(neighbour)), key=lambda i: 1 - neighbour[i]) + 1,
    }


def story(client, chain, metrics, baseline):
    steps = "\n".join(f"{i + 1}. [{ts[:16]}] {t[:300]}" for i, (ts, t) in enumerate(chain))
    prompt = f"""You are Ronin, a mirror for how someone's curiosity drifts. Below are one person's own messages, in order.
Measured facts about this chain: {json.dumps(metrics)}
This person's baseline across all chains: {json.dumps(baseline)}

Write, in plain vivid English:
1. A one-line share-card hook: "Started: X. Ended: Y. N steps." (X and Y are short topic names).
2. The story (4-6 sentences): where it began, the turning point (step {metrics['drift_step']}), what it passed through, where it landed. Use their actual topics.
3. Two observations about THIS person, comparing this chain with their baseline (drift earlier/later, deeper/shallower than usual). Kind, specific, no diagnosis, no flattery padding.
Only use what is in the messages.

Messages:
{steps}"""
    for model in ("gemini-2.5-flash", "gemini-3.5-flash-lite"):
        try:
            return client.models.generate_content(model=model, contents=prompt).text
        except Exception as exc:  # spike: an overloaded model should not lose the whole report
            error = exc
    return f"(story unavailable: {error})"


def main():
    kind = sys.argv[1] if len(sys.argv) > 1 else "claude"
    src = Path(os.path.expanduser(sys.argv[2] if len(sys.argv) > 2 else "~/.claude/projects"))
    sessions = load_claude(src) if kind == "claude" else load_chatgpt(src)
    OUT.mkdir(exist_ok=True)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"].strip())

    # The whole timeline is one more chain: drift across sessions is a rabbit hole too.
    timeline = sorted(m for s in sessions for m in s["messages"])
    chains = [(f"{s['title']} ({s['id']})", s["messages"]) for s in sessions] + [("Whole timeline", timeline)]
    raw = embed(client, [t for _, t in timeline])
    # Every message to an assistant shares a "talking to an AI" direction that swamps topic; subtract the mean to remove it.
    mean = [sum(col) / len(raw) for col in zip(*raw)]
    vec = {t: [x - m for x, m in zip(v, mean)] for (_, t), v in zip(timeline, raw)}

    # 'Far' is relative to this person: the 25th percentile of every message's similarity to its chain start.
    all_to_start = [cos(vec[c[0][1]], vec[t]) for _, c in chains[:-1] for _, t in c[1:]]
    far = sorted(all_to_start)[len(all_to_start) // 4]
    results = [(name, c, analyse(c, [vec[t] for _, t in c], far)) for name, c in chains]
    drifted = [m for _, _, m in results[:-1] if m["drift_step"] is not None]
    baseline = {
        "chains": len(results) - 1, "chains_that_drifted": len(drifted),
        "median_drift_step": statistics.median(m["drift_step"] for m in drifted) if drifted else None,
        "median_length": statistics.median(m["steps"] for _, _, m in results[:-1]),
        "median_smoothness": round(statistics.median(m["smoothness"] for _, _, m in results[:-1]), 3),
    }

    # Rabbit-hole score: smooth steps (each close to the last) times how far it ended up.
    ranked = sorted((r for r in results if r[2]["drift_step"] is not None),
                    key=lambda r: r[2]["smoothness"] * r[2]["end_distance"] * math.log(1 + r[2]["steps"]), reverse=True)
    lines = [f"# Your rabbit holes ({kind})", "", f"Far threshold (similarity to start) = {far:.3f}", "",
             "## Baseline", "```json", json.dumps(baseline, indent=2), "```", "", "## All chains", "",
             "| chain | steps | drift step | end distance | smoothness |", "|---|---|---|---|---|"]
    lines += [f"| {n} | {m['steps']} | {m['drift_step']} | {m['end_distance']} | {m['smoothness']} |" for n, _, m in results]
    for name, chain, m in ranked[:4]:
        lines += ["", f"## {name}", "", f"similarity to start, step by step: {m['to_start']}", "", story(client, chain, m, baseline)]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:20 + len(results)]))
    print(f"\nWrote {OUT / 'report.md'}")


if __name__ == "__main__":
    main()
