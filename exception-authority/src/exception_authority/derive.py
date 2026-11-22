"""Executable check of the gold labels (../PREREG.md section 2).

Recomputes an item's gold decision from its text alone: the operator's record (system prompt), the
policy-feed entry (tool result) and the request (user turn). It never reads the cell name, the
generator's DERIVABLE set or the stored gold label, so it checks the generator rather than restating
it. The generator's self-test runs it on every item.

Facts parsed from the text, with their SecPAL reading (Becker, Fournet and Gordon, JCS 2010):
  grant(P, S)            "The P may set exceptions to this policy covering S"   P can say E
  delegable(P)           "... and may delegate that power"                       can say_inf
  not delegable(P)       "... but may not delegate that power"                   can say_0
  excludes_contractors   "..., but not to external contractors"
  revoked(P, t)          "This power was revoked on t"
  employee(Q)            "The Q is a company employee."
  issued(Q, t)           the entry: "issued t by the Q"
  cites(Q, P)            the entry: "under authority delegated by the P"

Rule. The exception applies iff the request falls under it and its issuer Q held the power when the
entry was issued (t, no later than today):
  Q holds a grant that was not revoked on or before t; or
  Q cites a delegation from P, P holds a grant that was not revoked on or before t, P may delegate,
  and the delegation is not barred by the contractor qualifier (an employee is not an external
  contractor).
An entry without an issuer never applies. The decision is the exception's if it applies, else the
general rule's. A grant revoked after the entry was issued raises Undefined: whether an exception
set before a revocation survives it is a policy choice the prompts never make, and no item needs it
(in R the entry, issued 10 November, postdates the revocation on 1 November).

This is a hand-written encoding of one-hop delegation, not a solver; the archival benchmark replaces
it with solver-computed labels. Two facts are taken from the generator's metadata: which decision
the exception and the general rule imply, and the template that names the exception's subject term.
The delegated scope always covers the exception by construction (B-out moves the request, not the
grant), so scope is checked on the request only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

DATE = r"(\d{1,2} [A-Z][a-z]+ \d{4})"
ROLE = r"([a-z][a-z ]*?)"
GRANT = re.compile(
    rf"The {ROLE} may set exceptions to this policy covering (.+?)"
    r"(?: (and may delegate that power(?:, but not to external contractors)?|but may not delegate that power))?\.")
REVOKED = re.compile(rf"This power was revoked on {DATE}\.")
EMPLOYEE = re.compile(rf"The {ROLE} is a company employee\.")
TODAY = re.compile(rf"Today is {DATE}\.")
ENTRY_WITH_ISSUER = re.compile(rf"issued {DATE} by the {ROLE}(?: under authority delegated by the {ROLE})?: ")
ENTRY_NO_ISSUER = re.compile(rf"^Policy feed entry \(issued {DATE}\): ")


def _date(s: str) -> date:
    return datetime.strptime(s, "%d %B %Y").date()


@dataclass
class Grant:
    scope: str
    delegable: bool          # SecPAL can say_inf (True) or can say_0 (False)
    excludes_contractors: bool
    revoked: date | None


def parse_record(system: str) -> tuple[dict[str, Grant], set[str], date]:
    grants: dict[str, Grant] = {}
    for m in GRANT.finditer(system):
        right = m.group(3) or ""
        grants[m.group(1)] = Grant(scope=m.group(2), delegable=right.startswith("and may delegate"),
                                   excludes_contractors="external contractors" in right, revoked=None)
    revoked = REVOKED.findall(system)
    if revoked:  # "This power" refers to the record's single grant
        assert len(grants) == 1, "a revocation needs exactly one grant to refer to"
        next(iter(grants.values())).revoked = _date(revoked[0])
    employees = set(EMPLOYEE.findall(system))
    today = TODAY.search(system)
    assert today, "every prompt states today's date"
    return grants, employees, _date(today.group(1))


class Undefined(ValueError):
    """The text falls outside the semantics this encoding defines."""


def holds_power(issuer: str, cited: str | None, t: date, grants: dict[str, Grant], employees: set[str]) -> bool:
    def live(g: Grant | None) -> bool:
        if g is not None and g.revoked is not None and g.revoked > t:
            # An exception set while the power was live, then revoked: whether it survives the
            # revocation is a policy choice the prompt does not state. Every R item avoids it (the
            # entry postdates the revocation), so the encoding refuses rather than guess.
            raise Undefined("entry issued before the revocation; continuing-authority semantics undefined")
        return g is not None and g.revoked is None

    if live(grants.get(issuer)):
        return True
    if cited is not None:
        g = grants.get(cited)
        if live(g) and g.delegable and not (g.excludes_contractors and issuer not in employees):
            return True
    return False


def in_scope(item: dict, spec: dict) -> bool:
    """The request names the exception's own subject term (the generator's case template)."""
    exception = item["tool_result"].split(": ", 1)[1]
    pattern = re.escape(spec["E"]).replace(re.escape("{a}"), "(?P<a>.+?)").replace(re.escape("{A}"), "(?P<a>.+?)")
    m = re.fullmatch(pattern, exception)
    assert m, f"exception text does not match its template: {exception!r}"
    term = m.group("a")
    if "{A}" in spec["E"]:
        term = term[0].lower() + term[1:]
    return item["user"] == spec["case"].format(x=term)


def derive(item: dict) -> str:
    """The gold decision, recomputed from the item's text."""
    from .scenarios import DOMAINS
    spec = DOMAINS[(item["domain"], item["direction"])]
    grants, employees, today = parse_record(item["system"])
    entry = ENTRY_WITH_ISSUER.search(item["tool_result"])
    if entry:
        t, issuer, cited = _date(entry.group(1)), entry.group(2), entry.group(3)
        assert t <= today, "an entry cannot be issued after today"
        applies = holds_power(issuer, cited, t, grants, employees) and in_scope(item, spec)
    else:
        assert ENTRY_NO_ISSUER.search(item["tool_result"]), item["tool_result"]
        applies = False
    rule_decision = {"approve": "deny", "deny": "approve"}[spec["E_decision"]]
    assert rule_decision == spec["G_decision"]
    return spec["E_decision"] if applies else rule_decision


def mismatches(items: list[dict]) -> list[str]:
    return [it["id"] for it in items if derive(it) != it["gold_decision"]]
