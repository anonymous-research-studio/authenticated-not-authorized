"""The spending guard: cap, confirmation, worst-case reservation, drift and failure stops, ledger."""
import json
import unittest

from exception_authority import guard, runner

from .support import Harness


class TestGuard(Harness):
    def test_paid_needs_cap_and_confirmation(self):
        with self.assertRaises(SystemExit):
            self.run_("paid")                       # no --max-cost
        with self.assertRaises(SystemExit):
            self.run_("paid", "--max-cost", "100")  # no --yes, not a terminal
        self.assertEqual(self.rows("paid", "scripted-paid"), [])

    def test_cap_is_never_exceeded(self):
        self.assertEqual(self.run_("paid", "--max-cost", "3", "--yes"), 1)  # below one request's worst case
        self.assertEqual(self.rows("paid", "scripted-paid"), [])
        for workers in ("1", "4"):
            self.run_("paid", "--max-cost", "12", "--yes", "--workers", workers)
        self.assertTrue(self.rows("paid", "scripted-paid"))
        ledger = runner.load_jsonl(self.results / "spend-ledger.jsonl")
        self.assertEqual(len(ledger), 3)
        for entry in ledger:
            self.assertLessEqual(entry["spent_command_total"], entry["cap"])

    def test_cost_drift_stops_the_run(self):
        # Ten logged rows with tiny token counts make the estimate far below the real cost.
        fake = self.results / "check" / "scripted-paid.jsonl"
        fake.parent.mkdir(parents=True)
        fake.write_text("".join(json.dumps({"usage": {"input_tokens": 1, "output_tokens": 1}}) + "\n" for _ in range(10)))
        self.assertEqual(self.run_("paid", "--max-cost", "1000", "--yes", "--workers", "1"), 1)
        self.assertEqual(len(self.rows("paid", "scripted-paid")), guard.DRIFT_MIN_ROWS)
        self.assertTrue(runner.load_jsonl(self.results / "spend-ledger.jsonl")[0]["cost_drift"])

    def test_fatal_error_stops_at_once_and_streak_stops(self):
        self.assertEqual(self.run_("bad", "--model", "scripted-fatal", "--workers", "1"), 1)
        errs = runner.load_jsonl(self.results / "bad" / "scripted-fatal.errors.jsonl")
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["fatal"], "authentication or permission")
        self.assertEqual(self.run_("bad", "--model", "scripted-flaky", "--workers", "1"), 1)
        errs = runner.load_jsonl(self.results / "bad" / "scripted-flaky.errors.jsonl")
        self.assertEqual(len(errs), guard.MAX_CONSECUTIVE_FAILURES)

    def test_attempt_limit(self):
        for _ in range(3):
            self.run_("bad", "--model", "scripted-flaky", "--workers", "1")
        # 30 failures over 54 items, in a seeded order: some items have used all their attempts.
        todo, _, exhausted = runner.pending("scripted-flaky", {"provider": "scripted", "policy": "flaky"},
                                            self.items("check"), self.results / "bad" / "x.jsonl",
                                            self.results / "bad" / "scripted-flaky.errors.jsonl", "bad", None)
        self.assertEqual(len(todo) + len(exhausted), 54)

    def test_unpriced_paid_model_refused(self):
        with self.assertRaises(SystemExit):
            self.run_("router", "--dry-run")

    def test_cache_pricing_and_worst_case(self):
        m = {"provider": "anthropic", "price_in": 4.0, "price_out": 20.0, "price_cache_write": 5.0,
             "price_cache_read": 0.2, "max_tokens": 4000}
        self.assertAlmostEqual(guard.cost(m, 0, 100, cache_write=1000), (1000 * 5 + 100 * 20) / 1e6)
        self.assertAlmostEqual(guard.cost(m, 10, 100, cache_read=1000), (10 * 4 + 1000 * 0.2 + 100 * 20) / 1e6)
        item = {"system": "s" * 600, "user": "u" * 60, "tool_result": "t" * 120}
        h = 2 * guard.heuristic_input_tokens(item)
        self.assertAlmostEqual(guard.worst_case(m, item, cache=True), (h * 5 + 4000 * 20) / 1e6)
        self.assertGreater(guard.worst_case(m, item, cache=True), guard.worst_case(m, item))
        class U:  # an Anthropic-style usage object with cache fields
            input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens = 0, 50, 0, 1000
        self.assertAlmostEqual(guard.usage_cost(m, U), (1000 * 0.2 + 50 * 20) / 1e6)
        # a reply can never cost more than its reservation, cached or not
        for cw, cr in ((h, 0), (0, h), (0, 0)):
            self.assertLessEqual(guard.cost(m, h - cw - cr, 4000, cw, cr), guard.worst_case(m, item, cache=True) + 1e-12)


if __name__ == "__main__":
    unittest.main()
