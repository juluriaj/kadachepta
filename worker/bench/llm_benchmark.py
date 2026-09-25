"""Compare local LLMs on teaser drafting for real Telugu transcripts.

    python worker/bench/llm_benchmark.py --models qwen/qwen3-8b google/gemma-3-12b --transcripts catalog/transcripts

Writes docs/benchmarks/teaser-<date>.md (side-by-side outputs for human review) and a JSON file with raw results.
Automatic checks: valid JSON, every language present, length limits, share of text written in the right script,
English leaking into the Telugu teaser, speed. Factual accuracy and spoilers still need a human read.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kc_worker import llm  # noqa: E402
from kc_worker.handlers.teaser import SCHEMA_V4 as SCHEMA, build_messages, validate  # noqa: E402

SCRIPT_PREFIX = {"te-IN": "TELUGU", "hi-IN": "DEVANAGARI", "ta-IN": "TAMIL", "kn-IN": "KANNADA"}


def script_share(text: str, language: str) -> float | None:
    prefix = SCRIPT_PREFIX.get(language)
    letters = [ch for ch in text if ch.isalpha()]
    if not prefix or not letters:
        return None
    return round(sum(unicodedata.name(ch, "").startswith(prefix) for ch in letters) / len(letters), 3)


def load_transcripts(folder: Path, limit: int) -> list[dict]:
    items = []
    for path in sorted(folder.glob("*.json"))[:limit]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        text = raw.get("transcript") or raw.get("text") or ""
        if text.strip():
            items.append({"id": path.stem.split(".")[0], "title": raw.get("title") or path.stem, "text": text})
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--transcripts", type=Path, default=Path("catalog/transcripts"))
    parser.add_argument("--titles", type=Path, help="Optional JSON {assetId: title}")
    parser.add_argument("--languages", nargs="+", default=["te-IN", "en-IN"])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--out", type=Path, default=Path("docs/benchmarks"))
    args = parser.parse_args()

    available = llm.list_models()
    missing = [m for m in args.models if m not in available]
    if missing:
        print(f"Not available in LM Studio: {missing}. Available: {available}")
        return 2
    titles = json.loads(args.titles.read_text(encoding="utf-8")) if args.titles else {}
    stories = load_transcripts(args.transcripts, args.limit)
    if not stories:
        print(f"No transcripts found in {args.transcripts}")
        return 2
    results = []
    for model in args.models:
        for story in stories:
            title = titles.get(story["id"], story["title"])
            started = time.monotonic()
            entry = {"model": model, "assetId": story["id"], "title": title, "chars": len(story["text"])}
            try:
                output, stats = llm.chat_json(build_messages(title, story["text"], args.languages), SCHEMA, model=model)
                texts = {item.get("language"): item for item in output.get("texts", [])}
                primary = texts.get(args.languages[0], {})
                entry.update(ok=True, output=output, stats=stats, problems=validate(output, args.languages),
                             scriptShare=script_share(primary.get("long", "") + primary.get("short", ""), args.languages[0]),
                             longWords={lang: len((texts.get(lang) or {}).get("long", "").split()) for lang in args.languages})
            except llm.LlmError as error:
                entry.update(ok=False, error=str(error), seconds=round(time.monotonic() - started, 1))
            results.append(entry)
            status = "ok" if entry.get("ok") and not entry.get("problems") else entry.get("error") or entry.get("problems")
            print(f"{model:28} {story['id']} {entry.get('stats', {}).get('seconds', '?')}s {status}")
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.out / f"teaser-{date.today():%Y-%m-%d}"
    stem.with_suffix(".json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    stem.with_suffix(".md").write_text(render(results, args.models, args.languages), encoding="utf-8")
    print(f"Report: {stem.with_suffix('.md')}")
    return 0


def render(results: list[dict], models: list[str], languages: list[str]) -> str:
    lines = ["# Local LLM teaser benchmark", "", f"Date: {date.today():%Y-%m-%d}. Languages: {', '.join(languages)}.", "",
             "## Summary", "", "| Model | Stories | Valid | Avg seconds | Avg tokens/s | Avg script share |",
             "|---|---|---|---|---|---|"]
    for model in models:
        rows = [r for r in results if r["model"] == model]
        valid = [r for r in rows if r.get("ok") and not r.get("problems")]
        secs = [r["stats"]["seconds"] for r in rows if r.get("ok")]
        tps = [r["stats"].get("tokensPerSecond") for r in rows if r.get("ok") and r["stats"].get("tokensPerSecond")]
        share = [r["scriptShare"] for r in rows if r.get("scriptShare") is not None]
        avg = lambda values: f"{sum(values) / len(values):.1f}" if values else "–"  # noqa: E731
        lines.append(f"| {model} | {len(rows)} | {len(valid)} | {avg(secs)} | {avg(tps)} | "
                     f"{(sum(share) / len(share)):.0%} |" if share else f"| {model} | {len(rows)} | {len(valid)} | {avg(secs)} | {avg(tps)} | – |")
    lines += ["", "Script share = fraction of letters in the Telugu teaser that are Telugu script (1.0 = no English leakage).",
              "", "## Outputs for human review", ""]
    for asset_id in dict.fromkeys(r["assetId"] for r in results):
        story_rows = [r for r in results if r["assetId"] == asset_id]
        lines += [f"### {story_rows[0]['title']} (`{asset_id}`)", ""]
        for row in story_rows:
            lines.append(f"**{row['model']}**" + (f" — {row['stats']['seconds']}s" if row.get("ok") else ""))
            if not row.get("ok"):
                lines += [f"- Error: {row.get('error')}", ""]
                continue
            texts = {item.get("language"): item for item in row["output"].get("texts", [])}
            for language in languages:
                item = texts.get(language, {})
                lines.append(f"- {language} short: {item.get('short', '—')}")
                lines.append(f"- {language} long: {item.get('long', '—')}")
            out = row["output"]
            lines.append(f"- Themes: {', '.join(out.get('themes', []))} · Mood: {', '.join(out.get('mood', []))} · "
                         f"Age: {out.get('ageSuggestion')} · Warnings: {', '.join(out.get('contentWarnings', [])) or 'none'}")
            lines.append(f"- Moral: {out.get('moralTakeaway')}")
            if row.get("problems"):
                lines.append(f"- Problems: {'; '.join(row['problems'])}")
            lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
