#!/usr/bin/env python3
"""Used by 09_export_anonymous.sh on the staged copy only (never on results/ itself). Removes provider
request, generation and account identifiers from the exported results, then fails if any remain.

- In every .jsonl and .json file under results/: drops the keys request_id and request_ids at any depth,
  and replaces any provider ID left inside a string with "[id removed]".
- In every other text file under results/ (logs, scripts): replaces provider IDs with "[id removed]".
- Then scans the whole export for the ID patterns and exits 1 on any match.

No decision, label, token count, cost, hash or timestamp is changed, so the scorer gives the same output
on the export as on the original results. Our own prefilled tool-call ids (call_PolicyFeedLookup, toolu_01PolicyFeedLookup) are part
of the prompt and are kept.
Usage: python -I scripts/scrub_export.py EXPORT_DIR
"""
import json
import re
import sys
from pathlib import Path

DROP_KEYS = {"request_id", "request_ids"}
KEEP = {"call_PolicyFeedLookup", "toolu_01PolicyFeedLookup"}  # our own prefilled tool-call ids (runner.py)
ID = re.compile(
    r"gen-\d{6,}-[A-Za-z0-9]{8,}"            # OpenRouter generation id
    r"|(?:req|msg|toolu|srvtoolu)_[A-Za-z0-9]{10,}"  # Anthropic request, message and tool-use ids
    r"|chatcmpl-[A-Za-z0-9]{10,}|call_[A-Za-z0-9]{10,}"  # OpenAI-style completion and tool-call ids
    r"|(?:org|user|acct|proj)[-_][A-Za-z0-9]{10,}"  # organization, user, account and project ids
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # UUIDs (e.g. organization ids)
)


def redact(s: str) -> str:
    return ID.sub(lambda m: m.group(0) if m.group(0) in KEEP else "[id removed]", s)


def clean(obj):
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items() if k not in DROP_KEYS}
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    return redact(obj) if isinstance(obj, str) else obj


def scrub(results: Path) -> int:
    changed = 0
    for p in sorted(results.rglob("*")):
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if p.suffix == ".jsonl":
            new = "".join(json.dumps(clean(json.loads(line)), ensure_ascii=False) + "\n"
                          for line in text.splitlines() if line.strip())
        elif p.suffix == ".json":
            new = json.dumps(clean(json.loads(text)), indent=2, ensure_ascii=False) + "\n"
        else:
            new = redact(text)
        if new != text:
            p.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def remaining(root: Path) -> list[str]:
    hits = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        found = [m.group(0) for m in ID.finditer(text) if m.group(0) not in KEEP]
        keys = [k for k in DROP_KEYS if f'"{k}"' in text] if p.suffix in (".jsonl", ".json") else []
        if found or keys:
            hits.append(f"{p.relative_to(root)}: {len(found)} id(s), keys {keys}")
    return hits


def main(argv):
    root = Path(argv[0])
    results = root / "exception-authority" / "results"
    n = scrub(results) if results.exists() else 0
    hits = remaining(root)
    if hits:
        print("FAIL: provider ids remain in the export:\n  " + "\n  ".join(hits))
        return 1
    print(f"ids removed from {n} results file(s); no request, generation or account id remains in the export")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
