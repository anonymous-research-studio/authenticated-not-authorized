"""Spending guard for runs that call paid models.

Policy, enforced by runner.py:
1. A cost estimate is printed before anything is sent: from this model's logged rows in any stage
   (exact token counts), or, with no rows yet, a deliberately high default.
2. A paid run never starts without a hard cap (--max-cost, USD) and an explicit confirmation: a typed
   "yes" in a terminal, or --yes when run non-interactively, only after the person paying approved it.
3. Before each request, its worst case (input tokens plus max_tokens of output) is reserved against
   the cap. A request that could push spend past the cap is not sent. Because the reservation is the
   worst case, not an average, spend cannot exceed the cap even with parallel workers.
4. An account or request error (bad or missing key, no credit, unknown model, malformed request)
   stops the model's run at once; so do ten failures in a row.
5. Cost drift: once 20 requests have finished in a run, if they cost more than 1.5 times the estimate
   on average, nothing more starts. Rerunning shows a new estimate from the logged rows, for approval.
6. Every paid run is appended to results/spend-ledger.jsonl, also when it stops early.
"""

from __future__ import annotations

import json
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_OUT_TOKENS = 2000      # output (thinking + answer) assumed when no rows are logged: high on purpose
TOOL_OVERHEAD_TOKENS = 600     # tool-use system prompt (286 per the pricing page), tool and output schemas
CHARS_PER_TOKEN = 3.0          # conservative: real English text runs closer to 4 characters per token
MIN_OWN_ROWS = 10              # rows needed before an estimate uses this model's own logs
COST_DRIFT = 1.5
DRIFT_MIN_ROWS = 20
MAX_CONSECUTIVE_FAILURES = 10


def is_paid(model_cfg: dict) -> bool:
    return model_cfg.get("provider") != "scripted" or model_cfg.get("price_in") is not None


def cost(model_cfg: dict, tokens_in: float, tokens_out: float,
         cache_write: float = 0, cache_read: float = 0) -> float:
    """tokens_in is the uncached input (Anthropic's input_tokens excludes cached tokens); cache writes and
    reads are priced at their own rates, falling back to the input price if a model has none."""
    if not is_paid(model_cfg):
        return 0.0
    pin = model_cfg["price_in"]
    return (tokens_in * pin + cache_write * model_cfg.get("price_cache_write", pin)
            + cache_read * model_cfg.get("price_cache_read", pin) + tokens_out * model_cfg["price_out"]) / 1e6


def usage_cost(model_cfg: dict, usage) -> float:
    """Cost of one response from its usage object, cache fields included (absent or None count as 0)."""
    return cost(model_cfg, usage.input_tokens, usage.output_tokens,
                getattr(usage, "cache_creation_input_tokens", 0) or 0, getattr(usage, "cache_read_input_tokens", 0) or 0)


def heuristic_input_tokens(item: dict) -> float:
    chars = len(item["system"]) + len(item["user"]) + len(item["tool_result"])
    return chars / CHARS_PER_TOKEN + TOOL_OVERHEAD_TOKENS


def worst_case(model_cfg: dict, item: dict, cache: bool = False) -> float:
    """Twice the (already high) input heuristic plus a full max_tokens of output: no request can cost more.
    Under the fallback feed protocol an item takes two calls, and call 2 also reads call 1's output.
    With caching, every input token is priced at the cache-write rate, the dearest way it can be billed."""
    tin, mx = 2 * heuristic_input_tokens(item), model_cfg.get("max_tokens", 4000)

    def one(n_in: float) -> float:
        return cost(model_cfg, 0, mx, cache_write=n_in) if cache else cost(model_cfg, n_in, mx)
    if model_cfg.get("feed_protocol") == "model_call":
        return one(tin) + one(tin + mx)
    return one(tin)


def logged_tokens(results_root: Path, model_name: str) -> tuple[float, float, int] | None:
    """Mean input and output tokens over every logged row of this model, in any stage."""
    tin = tout = n = 0
    for path in results_root.glob(f"*/{model_name}.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                u = json.loads(line)["usage"]
                total_in = u["input_tokens"] + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                tin, tout, n = tin + total_in, tout + u["output_tokens"], n + 1
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    return (tin / n, tout / n, n) if n >= MIN_OWN_ROWS else None


@dataclass
class Plan:
    model: str
    items: int
    paid: bool
    per_item: float
    worst_per_item: float
    basis: str

    @property
    def estimate(self) -> float:
        return self.per_item * self.items


def plan(model_name: str, model_cfg: dict, todo: list[dict], results_root: Path, cache: bool = False) -> Plan:
    """The estimate prices all input at the base rate (cache savings are not counted in advance); the
    worst case prices it at the cache-write rate when caching is on."""
    if not is_paid(model_cfg):
        return Plan(model_name, len(todo), False, 0.0, 0.0, "free (scripted)")
    worst = max((worst_case(model_cfg, it, cache) for it in todo), default=0.0)
    logged = logged_tokens(results_root, model_name)
    if logged:
        tin, tout, n = logged
        basis = f"mean of {n} logged rows"
    else:
        tin = sum(heuristic_input_tokens(it) for it in todo) / max(1, len(todo))
        tout = DEFAULT_OUT_TOKENS
        basis = f"no logs yet: high default ({DEFAULT_OUT_TOKENS} output tokens)"
        if model_cfg.get("feed_protocol") == "model_call":  # two calls; call 2 reads call 1's output
            tin, tout = 2 * tin + DEFAULT_OUT_TOKENS, 2 * DEFAULT_OUT_TOKENS
            basis += ", two calls per item"
    return Plan(model_name, len(todo), True, cost(model_cfg, tin, tout), worst, basis)


def format_plans(plans: list[Plan], cap: float | None) -> str:
    lines = [f"{'model':<20}{'items':>7}{'est. $/item':>13}{'worst $/item':>14}{'est. total':>12}  basis"]
    for p in plans:
        if p.paid:
            lines.append(f"{p.model:<20}{p.items:>7}{p.per_item:>13.5f}{p.worst_per_item:>14.5f}"
                         f"{'$' + format(p.estimate, ',.2f'):>12}  {p.basis}")
        else:
            lines.append(f"{p.model:<20}{p.items:>7}{'free':>13}{'free':>14}{'-':>12}  {p.basis}")
    total = sum(p.estimate for p in plans if p.paid)
    worst = sum(p.worst_per_item * p.items for p in plans if p.paid)
    lines.append(f"estimated spend: ${total:,.2f}   worst case if every reply hit max_tokens: ${worst:,.2f}"
                 + (f"   hard cap: ${cap:,.2f}" if cap is not None else ""))
    return "\n".join(lines)


def confirm(plans: list[Plan], max_cost: float | None, yes: bool) -> None:
    """Exit unless a paid run has a hard cap and an explicit confirmation."""
    paid = [p for p in plans if p.paid and p.items]
    if not paid:
        return
    if max_cost is None:
        sys.exit("This run calls paid models. Nothing was sent. Set a hard cap with --max-cost USD.")
    total = sum(p.estimate for p in paid)
    if total > max_cost:
        print(f"note: the estimate (${total:,.2f}) exceeds the cap; requests stop before ${max_cost:,.2f} "
              "and the rest can be run later (reruns resume).")
    if yes:
        return
    if sys.stdin.isatty():
        if input(f"Spend up to ${max_cost:,.2f} on this run? Type yes to proceed: ").strip().lower() == "yes":
            return
        sys.exit("Not confirmed. Nothing was sent.")
    sys.exit("Not confirmed. Nothing was sent. Non-interactively, pass --yes only after the run and its cap "
             "have been approved.")


class Budget:
    """Thread-safe spend tracker. Each request reserves its worst case before it is sent."""

    def __init__(self, cap: float | None):
        self.cap = cap
        self.spent = 0.0
        self.reserved = 0.0
        self._lock = threading.Lock()

    def reserve(self, amount: float) -> bool:
        with self._lock:
            if self.cap is not None and self.spent + self.reserved + amount > self.cap + 1e-12:
                return False
            self.reserved += amount
            return True

    def settle(self, reserved: float, actual: float) -> None:
        with self._lock:
            self.reserved -= reserved
            self.spent += actual


def fatal_reason(exc: BaseException) -> str | None:
    """An error every further request would hit too: it stops the model's run and is not counted as
    one of the item's attempts. None for ordinary, retryable failures."""
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()
    if status in (401, 403):
        return "authentication or permission"
    if status == 402 or "credit balance" in text or "insufficient credits" in text:
        return "out of credit"
    if status == 404:
        return "model not found"
    if status in (400, 413, 422):
        return "request rejected: a harness bug, fix the request before rerunning"
    if isinstance(exc, TypeError) and ("api_key" in text or "authentication" in text):
        return "no credentials"
    return None


def record_spend(ledger: Path, entry: dict) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": datetime.now(UTC).isoformat(timespec="seconds"), **entry}) + "\n")
