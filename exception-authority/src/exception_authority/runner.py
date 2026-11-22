"""Run one stage of the self-asserted-authority study and record every decision.

Stages (resources/config.json): smoke (scripted, free) -> check -> pilot (go/no-go) -> main.

The exception reaches the model through the tool channel:
  user request -> assistant tool_use (lookup_policy_feed) -> tool_result (the feed entry)
and the model answers with JSON {"decision", "clarification_required"} through structured outputs.
Further tool calls are disabled (tool_choice none).

No refusal fallbacks: a fallback would answer with a different model and mix models within one
results file. Refusals are recorded as their own outcome.

Spending (guard.py): --dry-run prints the plan and estimate and sends nothing. A paid run needs
--max-cost and a typed "yes" (or --yes after approval). Each request's worst case is reserved
against the cap before it is sent. Every paid run is appended to results/spend-ledger.jsonl.

Usage:
  python scripts/02_run_stage.py smoke                         # scripted models, free
  python scripts/02_run_stage.py check --dry-run [--show 1]     # plan, estimate, one request printed
  python scripts/02_run_stage.py check --model claude-haiku-5-5 --max-cost 0.50
  python scripts/03_freeze_protocol.py                         # before the pilot: fingerprint the protocol
  python scripts/02_run_stage.py pilot --model claude-haiku-5-5 --max-cost 1

Credentials: ANTHROPIC_API_KEY for Claude models, and OPENROUTER_API_KEY (or the model's
api_key_env) for OpenAI-compatible models, from .env in the repository root or the shell (a variable already set in the
shell wins). Keys are passed to the SDKs explicitly, so a stored login on another account is never used.

OpenAI-compatible models (provider openai_compatible; OpenRouter in resources/config.json) get the same three
turns in Chat Completions form: system, user, an assistant tool call, the tool message; tool_choice
"none" and a strict json_schema response_format. Pin one host with allow_fallbacks false, so results do not depend on which host served a request.
Results: results/<stage>/<model>.jsonl; finished ids are skipped on rerun.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import guard
from . import scenarios as S
from .paths import CONFIG, ENV, FROZEN, RESULTS, ROOT, SCENARIOS

# The protocol fingerprinted by freeze(); paths relative to ROOT. health.py and outputs.py are not
# part of it: they never change what is sent or how it is scored.
FROZEN_FILES = ["src/exception_authority/scenarios.py", "src/exception_authority/derive.py", "src/exception_authority/runner.py",
                "src/exception_authority/guard.py",
                "src/exception_authority/scoring.py", "resources/scenarios.jsonl", "resources/config.json",
                "../PREREG.md"]
MAX_ATTEMPTS = 3

TOOL = {
    "name": "lookup_policy_feed",
    "description": "Look up current entries in the company's policy feed for a topic.",
    "input_schema": {
        "type": "object",
        "properties": {"topic": {"type": "string"}},
        "required": ["topic"],
        "additionalProperties": False,
    },
}

DECISION_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["approve", "deny"]},
            "clarification_required": {"type": "boolean"},
        },
        "required": ["decision", "clarification_required"],
        "additionalProperties": False,
    },
}
TOOL_USE_ID = "toolu_01PolicyFeedLookup"


# --- requests -------------------------------------------------------------------------------------

CACHE_CONTROL = {"type": "ephemeral"}  # default 5-minute lifetime


def caches(model_cfg: dict, stage_cfg: dict) -> bool:
    """Prompt caching runs only for Claude models, and only in stages that set it (PREREG section 2)."""
    return bool(stage_cfg.get("cache")) and model_cfg.get("provider") in ("anthropic", "scripted")


def build_request(item: dict, model_cfg: dict, cache: bool = False) -> dict:
    """With cache, one breakpoint on the tool_result block, the request's last block, so the whole request
    is cached: sample 1 writes it and samples 2-3 read it. Nothing the model reads changes."""
    if model_cfg.get("provider") == "openai_compatible":
        return build_chat_request(item, model_cfg)
    output_config: dict = {"format": DECISION_FORMAT}
    if model_cfg.get("effort"):
        output_config["effort"] = model_cfg["effort"]
    # Fixed explicitly, like effort: adaptive thinking is each Claude 5.5 model's default (Opus 5.5
    # cannot disable it), and sending it means a change of default cannot change the study.
    thinking = {"thinking": {"type": model_cfg["thinking"]}} if model_cfg.get("thinking") else {}
    return {
        "model": model_cfg.get("model_id", "scripted"),
        **thinking,
        "max_tokens": model_cfg.get("max_tokens", 4000),
        "system": item["system"],
        "tools": [TOOL],
        "tool_choice": {"type": "none"},
        "output_config": output_config,
        "messages": [
            {"role": "user", "content": item["user"]},
            {"role": "assistant",
             "content": [{"type": "tool_use", "id": TOOL_USE_ID, "name": TOOL["name"],
                          "input": {"topic": item["domain"].replace("_", " ")}}]},
            {"role": "user",
             "content": [{"type": "tool_result", "tool_use_id": TOOL_USE_ID, "content": item["tool_result"],
                          **({"cache_control": CACHE_CONTROL} if cache else {})}]},
        ],
    }


def protocol_of(model_cfg: dict) -> str:
    return model_cfg.get("feed_protocol", "prefill")


def build_lookup_call(item: dict, model_cfg: dict) -> dict:
    """Fallback protocol, call 1: the request alone, with the lookup tool available (tool_choice auto; forced
    tool use is rejected with thinking on). No output format yet, so the model is free to call the tool."""
    if model_cfg.get("provider") == "openai_compatible":
        req = build_chat_request(item, model_cfg)
        req["messages"] = req["messages"][:2]
        req["tool_choice"] = "auto"
        req.pop("response_format")
        return req
    req = build_request(item, model_cfg)
    req["messages"] = req["messages"][:1]
    req["tool_choice"] = {"type": "auto"}
    req["output_config"] = {k: v for k, v in req["output_config"].items() if k != "format"}
    if not req["output_config"]:
        req.pop("output_config")
    return req


def lookup_calls(resp) -> list[dict]:
    """The lookup tool calls in a call-1 response, as {id, input}; empty if the model did not call it."""
    return [{"id": c["id"], "input": c.get("input")} for c in getattr(resp, "tool_calls", None) or []
            if c.get("name") == TOOL["name"]]


def build_decision_call(item: dict, model_cfg: dict, first) -> dict:
    """Fallback protocol, call 2: call 1's assistant turn passed back unchanged (thinking, reasoning and
    tool-call blocks included), then the fixed feed entry as the result of every lookup call."""
    calls = lookup_calls(first)
    if model_cfg.get("provider") == "openai_compatible":
        req = build_chat_request(item, model_cfg)
        req["messages"] = req["messages"][:2] + [first.raw_message] + [
            {"role": "tool", "tool_call_id": c["id"], "content": item["tool_result"]} for c in calls]
        return req
    req = build_request(item, model_cfg)
    req["messages"] = [req["messages"][0],
                       {"role": "assistant", "content": first.raw_message},
                       {"role": "user", "content": [{"type": "tool_result", "tool_use_id": c["id"],
                                                     "content": item["tool_result"]} for c in calls]}]
    return req


def build_chat_request(item: dict, model_cfg: dict) -> dict:
    """The same conversation for a Chat Completions endpoint."""
    call_id = "call_PolicyFeedLookup"
    request: dict = {
        "model": model_cfg["model_id"],
        "max_tokens": model_cfg.get("max_tokens", 4000),
        "messages": [
            {"role": "system", "content": item["system"]},
            {"role": "user", "content": item["user"]},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": call_id, "type": "function",
                             "function": {"name": TOOL["name"],
                                          "arguments": json.dumps({"topic": item["domain"].replace("_", " ")})}}]},
            {"role": "tool", "tool_call_id": call_id, "content": item["tool_result"]},
        ],
        "tools": [{"type": "function", "function": {"name": TOOL["name"], "description": TOOL["description"],
                                                    "parameters": TOOL["input_schema"]}}],
        "tool_choice": "none",
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "decision", "strict": True, "schema": DECISION_FORMAT["schema"]}},
    }
    for key in ("temperature", "seed"):
        if model_cfg.get(key) is not None:
            request[key] = model_cfg[key]
    if model_cfg.get("extra_body"):
        request["extra_body"] = model_cfg["extra_body"]
    return request


def key_env(model_cfg: dict) -> str | None:
    if model_cfg.get("provider") == "anthropic":
        return "ANTHROPIC_API_KEY"
    if model_cfg.get("provider") == "openai_compatible":
        return model_cfg.get("api_key_env", "OPENROUTER_API_KEY")
    return None


def pinned_host(model_cfg: dict) -> str | None:
    order = ((model_cfg.get("extra_body") or {}).get("provider") or {}).get("order")
    return order[0].split("/")[0].lower() if order else None


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


PRICE_KEYS = ("price_in", "price_out", "price_cache_write", "price_cache_read", "note")


def settings_hash(model_cfg: dict) -> str:
    """Everything about a request except the scenario: a change starts a fresh results file. Prices and
    prompt caching (a stage setting that never changes what the model sees) are not part of it."""
    behavior = {k: v for k, v in model_cfg.items() if k not in PRICE_KEYS}
    return _digest({**behavior, "tool": TOOL, "format": DECISION_FORMAT})


def item_hash(item: dict) -> str:
    return _digest({k: item[k] for k in ("system", "user", "tool_result", "gold_decision", "exception_decision")})


def parse(text: str) -> tuple[str | None, bool | None, bool]:
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None, None, False
    if not isinstance(obj, dict):
        return None, None, False
    d, c = obj.get("decision"), obj.get("clarification_required")
    ok = d in ("approve", "deny") and isinstance(c, bool)
    return (d if d in ("approve", "deny") else None), (c if isinstance(c, bool) else None), ok


# --- scripted models (no API calls) ---------------------------------------------------------------

class ScriptedError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def to_dict(self) -> dict:
        return {k: (v.to_dict() if isinstance(v, _Obj) else v) for k, v in self.__dict__.items()}


def scripted_response(policy: str, item: dict, request: dict | None = None):
    flip = {"approve": "deny", "deny": "approve"}
    is_lookup_call = request is not None and request.get("tool_choice") in ({"type": "auto"}, "auto")
    if is_lookup_call and policy != "nolookup":  # call 1 of the fallback protocol: call the lookup tool
        block = _Obj(type="tool_use", id="toolu_scripted", name=TOOL["name"], input={"topic": item["domain"]})
        return _Obj(content=[block], stop_reason="tool_use", stop_details=None,
                    usage=_Obj(input_tokens=int(guard.heuristic_input_tokens(item) * 0.6), output_tokens=30),
                    model="scripted", _request_id=f"scripted-{item['id']}-1",
                    tool_calls=[{"id": "toolu_scripted", "name": TOOL["name"], "input": {"topic": item["domain"]}}],
                    raw_message=[block.to_dict()])
    if policy == "nolookup":
        policy = "gold"
    if policy == "fatal":
        raise ScriptedError("invalid x-api-key", status_code=401)
    if policy == "flaky":
        raise ScriptedError("overloaded", status_code=529)
    if policy == "garbage":
        text = "I would approve this one."
    else:
        decision = {"gold": item["gold_decision"], "accept": item["exception_decision"],
                    "never": flip[item["exception_decision"]]}[policy]
        text = json.dumps({"decision": decision, "clarification_required": False})
    tin = int(guard.heuristic_input_tokens(item) * 0.6)
    return _Obj(content=[_Obj(type="text", text=text)], stop_reason="end_turn", stop_details=None,
                usage=_Obj(input_tokens=tin, output_tokens=20), model="scripted",
                _request_id=f"scripted-{item['id']}")


# --- files ----------------------------------------------------------------------------------------

def load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines from .env into the environment; variables already set win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if value and key not in os.environ:
            os.environ[key] = value


def load_jsonl(path: Path) -> list[dict]:
    """Rows of a JSONL file; a truncated last line (an interrupted write) is skipped, so it reruns."""
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze() -> None:
    record = {"frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "files": {f: sha256_file((ROOT / f).resolve()) for f in FROZEN_FILES}}
    FROZEN.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {FROZEN.name}: {len(record['files'])} files fingerprinted. Record the freeze in PREREG.md's changelog.")


def frozen_problems() -> list[str]:
    if not FROZEN.exists():
        return ["no FROZEN.json: run `python scripts/03_freeze_protocol.py` after reviewing PREREG.md"]
    files = json.loads(FROZEN.read_text(encoding="utf-8"))["files"]
    return [f"{f} changed since the freeze" for f, h in files.items()
            if not (ROOT / f).resolve().exists() or sha256_file((ROOT / f).resolve()) != h]


# --- running --------------------------------------------------------------------------------------

def make_caller(model_cfg: dict):
    if model_cfg["provider"] == "scripted":
        seen: set[str] = set()
        lock = threading.Lock()

        def scripted(item: dict, request: dict):
            resp = scripted_response(model_cfg["policy"], item, request)
            last = request.get("messages", [{}])[-1].get("content")
            if isinstance(last, list) and last and "cache_control" in last[-1]:
                key = _digest(request)
                with lock:
                    hit = key in seen
                    seen.add(key)
                n = resp.usage.input_tokens
                resp.usage.input_tokens = 0
                resp.usage.cache_read_input_tokens = n if hit else 0
                resp.usage.cache_creation_input_tokens = 0 if hit else n
            return resp
        return scripted
    env = key_env(model_cfg)
    key = os.environ.get(env)
    if not key:
        sys.exit(f"{env} is not set (.env or the shell). Nothing was sent.")
    if model_cfg["provider"] == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=key, max_retries=4)  # the SDK retries 408/409/429/5xx with backoff

        def acall(item: dict, request: dict):
            resp = client.messages.create(**request)
            # For the fallback protocol: the turn to pass back unchanged, and its lookup calls.
            resp.raw_message = [b.to_dict() for b in resp.content]
            resp.tool_calls = [{"id": b.id, "name": b.name, "input": b.input}
                               for b in resp.content if getattr(b, "type", None) == "tool_use"]
            return resp
        return acall

    from openai import OpenAI
    oclient = OpenAI(base_url=model_cfg.get("base_url"), api_key=key, max_retries=4)

    def call(item: dict, request: dict):
        r = oclient.chat.completions.create(**request)
        choice = r.choices[0]
        if choice.finish_reason == "error":  # OpenRouter: the upstream host failed mid-response
            raise RuntimeError(f"provider returned finish_reason=error (response {r.id})")
        msg = choice.message
        refused = choice.finish_reason == "content_filter" or bool(getattr(msg, "refusal", None))
        u = r.usage
        if not msg.content and not refused and (not u or not u.completion_tokens):
            raise RuntimeError(f"empty response with 0 completion tokens (response {r.id})")  # retried, not scored
        stop = "refusal" if refused else {"stop": "end_turn", "length": "max_tokens",
                                          "tool_calls": "tool_use"}.get(choice.finish_reason, choice.finish_reason)
        raw = msg.model_dump(exclude_none=True)  # includes reasoning_details, passed back unchanged in call 2
        raw = {k: v for k, v in raw.items() if k in ("role", "content", "tool_calls", "reasoning", "reasoning_details")}
        calls = [{"id": c.id, "name": c.function.name, "input": c.function.arguments} for c in (msg.tool_calls or [])]
        return _Obj(content=[_Obj(type="text", text=msg.content or "")], stop_reason=stop, stop_details=None,
                    usage=_Obj(input_tokens=u.prompt_tokens if u else 0, output_tokens=u.completion_tokens if u else 0),
                    model=r.model, _request_id=r.id, served_by=(r.model_extra or {}).get("provider"),
                    tool_calls=calls, raw_message=raw)
    return call


def pending(name: str, model_cfg: dict, items: list[dict], out_path: Path, err_path: Path,
            stage: str, limit: int | None, samples: int = 1) -> tuple[list[dict], int, set]:
    """Items still to run, in a seeded random order (so a run cut short by the cap or --limit leaves
    gaps spread across cells, not the last domains). Refuses to mix settings or scenario texts."""
    rows = load_jsonl(out_path)
    want = settings_hash(model_cfg)
    if other := {r.get("settings_hash") for r in rows} - {want}:
        sys.exit(f"{out_path} holds rows written with other settings {sorted(map(str, other))}. Move it "
                 "aside (or rename the model in config.json) rather than mixing settings in one file.")
    by_id = {it["id"]: it for it in items}
    changed = [r["id"] for r in rows if r["id"] in by_id and r.get("item_hash") != item_hash(by_id[r["id"]])]
    if changed:
        sys.exit(f"{len(changed)} logged rows in {out_path} were run on different scenario text "
                 f"(e.g. {changed[0]}). Scenarios changed after these rows were written; move the file aside.")
    # One unit of work is (item, sample); sample 1 is the confirmatory reply (PREREG section 4).
    done = {(r["id"], r.get("sample", 1)) for r in rows}
    attempts: dict[tuple, int] = {}
    for e in load_jsonl(err_path):
        if not e.get("fatal"):
            key = (e["id"], e.get("sample", 1))
            attempts[key] = attempts.get(key, 0) + 1
    exhausted = {k for k, n in attempts.items() if n >= MAX_ATTEMPTS and k not in done}
    # Each item's remaining samples form one group, in sample order; groups are shuffled (seeded), so a
    # run cut short leaves gaps spread across cells. --limit counts items (groups). run_model runs a
    # group on one worker, one sample after another, so sample 2 starts only after sample 1 has returned.
    groups = [[{**it, "sample": k} for k in range(1, samples + 1)
               if (it["id"], k) not in done and (it["id"], k) not in exhausted] for it in items]
    groups = [g for g in groups if g]
    random.Random(f"{stage}:{name}").shuffle(groups)
    if limit:
        groups = groups[:limit]
    return [u for g in groups for u in g], len(done), exhausted


def run_model(name: str, model_cfg: dict, todo: list[dict], plan: guard.Plan, budget: guard.Budget,
              stage: str, out_path: Path, err_path: Path, workers: int, prov: dict, summary: dict,
              cache: bool = False) -> None:
    caller = make_caller(model_cfg)
    shash = settings_hash(model_cfg)
    stop = threading.Event()
    lock = threading.Lock()
    state = {"in_row": 0, "handled": 0}

    def work(item: dict):
        if stop.is_set():
            return "skipped", item, None
        reserve = guard.worst_case(model_cfg, item, cache)
        if not budget.reserve(reserve):
            stop.set()
            return "cap", item, None
        started = time.monotonic()
        calls = []  # every response billed for this item, in order
        try:
            if protocol_of(model_cfg) == "model_call":
                first = caller(item, build_lookup_call(item, model_cfg))
                calls.append(first)
                if lookup_calls(first) and first.stop_reason == "tool_use":
                    calls.append(caller(item, build_decision_call(item, model_cfg, first)))
            else:
                calls.append(caller(item, build_request(item, model_cfg, cache)))
        except Exception as exc:  # noqa: BLE001 - classified below
            spent = sum(guard.usage_cost(model_cfg, r.usage) for r in calls)
            budget.settle(reserve, spent)
            return "error", item, exc
        actual = sum(guard.usage_cost(model_cfg, r.usage) for r in calls)
        budget.settle(reserve, actual)
        return "ok", item, (calls, actual, time.monotonic() - started)

    def work_and_record(item: dict, out, err) -> None:
        # Recorded in the worker under a lock, so a stop (fatal error, streak, drift, cap) takes
        # effect before the next request is sent, not when the main thread gets round to it.
        result = work(item)
        with lock:
            handle(result, out, err)

    def handle(result, out, err) -> None:
        kind, item, payload = result
        if kind == "skipped":
            summary["skipped"] += 1
            return
        if kind == "cap":
            summary["skipped"] += 1
            summary["cap_reached"] = True
            return
        if kind == "error":
            exc = payload
            reason = guard.fatal_reason(exc)
            err.write(json.dumps({"id": item["id"], "sample": item.get("sample", 1),
                                  "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                  "error": type(exc).__name__, "status": getattr(exc, "status_code", None),
                                  "message": str(exc)[:500], "fatal": reason}) + "\n")
            err.flush()
            summary["errors"] += 1
            if reason:
                summary["fatal"] = summary["fatal"] or reason
                stop.set()
            else:
                state["in_row"] += 1
                if state["in_row"] >= guard.MAX_CONSECUTIVE_FAILURES:
                    summary["failure_streak"] = True
                    stop.set()
            return
        calls, actual, latency = payload
        resp = calls[-1]
        state["in_row"] = 0
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text")
        decision, clar, ok = parse(text)
        stop_details = getattr(resp, "stop_details", None)
        protocol = protocol_of(model_cfg)
        # Fallback protocol: a model that answers without calling the lookup tool never saw the entry.
        # The row is kept and logged as a protocol deviation; scoring treats it as invalid.
        deviation = None
        if protocol == "model_call" and len(calls) == 1 and resp.stop_reason not in ("refusal", "max_tokens"):
            deviation = "no_lookup"
        tin = sum(r.usage.input_tokens for r in calls)
        tout = sum(r.usage.output_tokens for r in calls)
        cw = sum(getattr(r.usage, "cache_creation_input_tokens", 0) or 0 for r in calls)
        cr = sum(getattr(r.usage, "cache_read_input_tokens", 0) or 0 for r in calls)
        row = {
            "id": item["id"], "sample": item.get("sample", 1), "stage": stage, "base": item["base"], "cell": item["cell"],
            "feed_protocol": protocol, "calls": len(calls), "protocol_deviation": deviation,
            "model": name, "model_id": model_cfg.get("model_id"), "served_model": getattr(resp, "model", None),
            "served_by": getattr(resp, "served_by", None), "pinned_host": pinned_host(model_cfg),
            "effort": model_cfg.get("effort"), "max_tokens": model_cfg.get("max_tokens"),
            "settings_hash": shash, "item_hash": item_hash(item),
            "request_id": getattr(resp, "_request_id", None) or getattr(resp, "id", None),
            "request_ids": [getattr(r, "_request_id", None) or getattr(r, "id", None) for r in calls],
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "latency_s": round(latency, 2),
            "stop_reason": resp.stop_reason,
            "refusal_category": getattr(stop_details, "category", None) if resp.stop_reason == "refusal" else None,
            # input_tokens is the uncached part; with caching the request's input is spread over the two cache fields
            "usage": {"input_tokens": tin, "output_tokens": tout,
                      "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr},
            "usage_per_call": [{"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens,
                                "cache_creation_input_tokens": getattr(r.usage, "cache_creation_input_tokens", 0) or 0,
                                "cache_read_input_tokens": getattr(r.usage, "cache_read_input_tokens", 0) or 0}
                               for r in calls],
            "cache_requested": cache,
            "cost_usd": round(actual, 6),
            "raw": text, "decision": decision, "clarification_required": clar, "parse_ok": ok,
            "provenance": prov,
        }
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
        out.flush()
        summary["ok"] += 1
        summary["cost"] += actual
        summary["tokens_in"] += tin + cw + cr
        summary["tokens_out"] += tout
        if model_cfg.get("model_id") and row["served_model"] and not str(row["served_model"]).startswith(model_cfg["model_id"]):
            summary["served_mismatch"] += 1
        if plan.paid and summary["ok"] >= guard.DRIFT_MIN_ROWS and not summary["cost_drift"]:
            if summary["cost"] / summary["ok"] > guard.COST_DRIFT * plan.per_item:
                summary["cost_drift"] = True
                stop.set()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    every = max(10, len({it["id"] for it in todo}) // 10)
    with out_path.open("a", encoding="utf-8") as out, err_path.open("a", encoding="utf-8") as err:
        pool = ThreadPoolExecutor(max_workers=workers)
        groups: list[list[dict]] = []
        for it in todo:  # pending() returns each item's samples contiguously, in sample order
            if groups and groups[-1][0]["id"] == it["id"]:
                groups[-1].append(it)
            else:
                groups.append([it])

        def run_group(group: list[dict]) -> None:
            for unit in group:  # sequential: sample k+1 is sent only after sample k's response returned
                work_and_record(unit, out, err)
        futures = [pool.submit(run_group, g) for g in groups]
        try:
            for n, fut in enumerate(as_completed(futures), 1):
                fut.result()
                if n % every == 0 and n < len(groups) and not stop.is_set():
                    print(f"  {name}: {n}/{len(groups)} items, {summary['errors']} errors, "
                          f"${summary['cost']:.4f}, {(time.monotonic() - started) / 60:.1f} min")
        except KeyboardInterrupt:
            stop.set()
            summary["interrupted"] = True
            cancelled = sum(f.cancel() for f in futures)
            summary["skipped"] += cancelled
            print(f"\n  {name}: INTERRUPTED; {cancelled} queued requests cancelled, waiting for the ones in "
                  "flight so their paid results are kept (Ctrl-C again to abandon them; they may still be billed)")
            try:
                pool.shutdown(wait=True)
            except KeyboardInterrupt:
                pass
        finally:
            pool.shutdown(wait=False, cancel_futures=True)


def provenance(scenarios: Path) -> dict:
    try:
        import anthropic
        sdk = anthropic.__version__
    except ImportError:
        sdk = None
    return {"runner_sha": sha256_file(Path(__file__))[:16], "guard_sha": sha256_file(Path(guard.__file__))[:16],
            "scenarios_sha": sha256_file(scenarios)[:16], "sdk": sdk,
            "python": platform.python_version(), "frozen": FROZEN.exists() and not frozen_problems()}


def main(argv: list[str]) -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=[*cfg["stages"], "freeze"])
    ap.add_argument("--model", action="append", help="run only this model (repeatable); default: the stage's models")
    ap.add_argument("--limit", type=int, help="at most this many items per model (a seeded random sample)")
    ap.add_argument("--max-cost", type=float, help="hard cap in USD for this whole command")
    ap.add_argument("--yes", action="store_true", help="confirm without a prompt; only after the run is approved")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and estimate; send nothing")
    ap.add_argument("--show", type=int, default=0, help="with --dry-run, print this many full requests")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--scenarios", type=Path, default=SCENARIOS)
    ap.add_argument("--results-dir", type=Path, default=RESULTS)
    args = ap.parse_args(argv)

    if args.stage == "freeze":
        freeze()
        return 0

    stage_cfg = cfg["stages"][args.stage]
    names = args.model or stage_cfg["models"]
    if unknown := [n for n in names if n not in cfg["models"]]:
        ap.error(f"unknown model(s) {unknown}; see resources/config.json")
    if args.model and (off := [n for n in names if n not in stage_cfg["models"]]):
        print(f"note: {off} not listed for stage {args.stage!r} in resources/config.json")
    items = [it for it in load_jsonl(args.scenarios) if it["stage"] == stage_cfg["scenarios"]]
    if not items:
        ap.error(f"no {stage_cfg['scenarios']!r} scenarios in {args.scenarios}; run scripts/01_generate_scenarios.py")

    if stage_cfg["frozen"] and (problems := frozen_problems()):
        msg = f"stage {args.stage!r} runs only on the frozen protocol: " + "; ".join(problems)
        if not args.dry_run:
            sys.exit(msg + ". Nothing was sent.")
        print("warning: " + msg)

    if unpriced := [n for n in names if cfg["models"][n]["provider"] != "scripted"
                    and (cfg["models"][n].get("price_in") is None or cfg["models"][n].get("price_out") is None)]:
        sys.exit(f"paid model(s) without price_in/price_out in resources/config.json: {unpriced}. Add the host's prices first.")

    # The feed protocol applies to every model alike. It enters each model's settings (and so its settings
    # hash) only when it is not the default, and the scenarios must have been generated for it.
    protocol = cfg.get("feed_protocol", "prefill")
    has_lookup = {S.LOOKUP_SENTENCE in it["system"] for it in items}
    if items and has_lookup != {protocol == "model_call"}:
        sys.exit(f"feed_protocol is {protocol!r} but the scenarios were generated for the other protocol. "
                 "Regenerate them (scripts/01_generate_scenarios.py). Nothing was sent.")
    model_cfgs = {n: ({**cfg["models"][n], "feed_protocol": protocol} if protocol != "prefill" else cfg["models"][n])
                  for n in names}
    stage_dir = args.results_dir / args.stage
    todos, plans, notes = {}, {}, []
    for name in names:
        out_path, err_path = stage_dir / f"{name}.jsonl", stage_dir / f"{name}.errors.jsonl"
        samples = int(stage_cfg.get("samples", {}).get(name, 1))
        todo, n_done, exhausted = pending(name, model_cfgs[name], items, out_path, err_path, args.stage, args.limit,
                                          samples)
        todos[name] = todo
        plans[name] = guard.plan(name, model_cfgs[name], todo, args.results_dir, caches(model_cfgs[name], stage_cfg))
        notes.append(f"{name}: {n_done} done, {len(todo)} to run"
                     + (f" ({samples} samples per item)" if samples > 1 else "") + (f", {len(exhausted)} given up after "
                                                                    f"{MAX_ATTEMPTS} failures" if exhausted else ""))
    print(f"stage {args.stage}: {stage_cfg['purpose']}")
    print(f"feed protocol: {protocol}" + ("; prompt caching on for the Claude models" if stage_cfg.get("cache") else ""))
    print("\n".join(notes))
    print(guard.format_plans(list(plans.values()), args.max_cost))

    if args.dry_run:
        for it in items[: args.show]:
            mc = model_cfgs[names[0]]
            req = build_lookup_call(it, mc) if protocol == "model_call" else build_request(it, mc)
            print(json.dumps(req, indent=2, ensure_ascii=False))
        envs = sorted({e for n in names if (e := key_env(cfg["models"][n]))})
        if envs:
            load_dotenv(ENV)
        for env in envs:
            print(f"{env}: " + ("found (value not shown)" if os.environ.get(env) else "NOT FOUND in .env or the shell"))
        print("dry run: nothing was sent.")
        return 0

    paid = [n for n in names if plans[n].paid and plans[n].items]
    if paid:
        load_dotenv(ENV)
        for n in paid:
            if (env := key_env(cfg["models"][n])) and not os.environ.get(env):
                sys.exit(f"{env} is not set for {n} (.env or the shell). Nothing was sent.")
    guard.confirm(list(plans.values()), args.max_cost, args.yes)

    budget = guard.Budget(args.max_cost if paid else None)
    prov = provenance(args.scenarios)
    ledger = args.results_dir / "spend-ledger.jsonl"
    stopped = False
    for name in names:
        if not todos[name]:
            continue
        if stopped:
            print(f"{name}: not started (an earlier model stopped the run)")
            continue
        summary = {"ok": 0, "errors": 0, "skipped": 0, "cost": 0.0, "tokens_in": 0, "tokens_out": 0,
                   "served_mismatch": 0, "fatal": None, "failure_streak": False, "cost_drift": False,
                   "cap_reached": False, "interrupted": False}
        n_items = len({u["id"] for u in todos[name]})
        print(f"{name}: running {len(todos[name])} requests ({n_items} items) with {args.workers} workers")
        try:
            run_model(name, model_cfgs[name], todos[name], plans[name], budget, args.stage,
                      stage_dir / f"{name}.jsonl", stage_dir / f"{name}.errors.jsonl", args.workers, prov, summary,
                      cache=caches(model_cfgs[name], stage_cfg))
        finally:  # the ledger is written even if the run stops on an error or an interrupt
            if plans[name].paid:
                guard.record_spend(ledger, {"stage": args.stage, "model": name, "cap": args.max_cost,
                                            "estimate": round(plans[name].estimate, 4),
                                            "spent_command_total": round(budget.spent, 6),
                                            **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in summary.items()}})
        print(f"{name}: {summary['ok']} ok, {summary['errors']} errors, {summary['skipped']} not started; "
              f"{summary['tokens_in']:,} tokens in, {summary['tokens_out']:,} out, about ${summary['cost']:.4f}")
        if summary["served_mismatch"]:
            print(f"{name}: WARNING: {summary['served_mismatch']} replies came from a different model than requested")
        if summary["fatal"]:
            print(f"{name}: STOPPED: {summary['fatal']}. No further requests were sent. Fix it, then rerun the same command.")
        elif summary["cost_drift"]:
            print(f"{name}: STOPPED: requests cost ${summary['cost'] / summary['ok']:.5f} on average, more than "
                  f"{guard.COST_DRIFT}x the ${plans[name].per_item:.5f} estimate. Rerun to see a new estimate for approval.")
        elif summary["failure_streak"]:
            print(f"{name}: STOPPED after {guard.MAX_CONSECUTIVE_FAILURES} failures in a row; rerun once the API recovers.")
        elif summary["cap_reached"]:
            print(f"{name}: STOPPED at the ${args.max_cost:,.2f} cap; rerun with a new approved cap to resume.")
        stopped = stopped or bool(summary["fatal"] or summary["failure_streak"] or summary["cost_drift"]
                                  or summary["cap_reached"] or summary["interrupted"])
    if paid:
        print(f"spend this command: about ${budget.spent:,.4f} of a ${args.max_cost:,.2f} cap (ledger: {ledger})")
    print(f"next: python scripts/04_health_check.py {args.stage}")
    return 1 if stopped else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
