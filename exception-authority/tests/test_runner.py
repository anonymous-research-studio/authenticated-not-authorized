"""The runner: stages, resume, health, no mixing of settings or text, the freeze, request shapes."""
import json
import unittest

from exception_authority import health, runner

from .support import Harness, quiet


class TestRunner(Harness):
    def test_smoke_runs_and_resumes(self):
        self.assertEqual(self.run_("smoke"), 0)
        for m in ("scripted-gold", "scripted-accept", "scripted-never", "scripted-garbage"):
            self.assertEqual(len(self.rows("smoke", m)), 54)
        self.run_("smoke")  # resume: nothing new
        self.assertEqual(len(self.rows("smoke", "scripted-gold")), 54)
        self.assertFalse((self.results / "spend-ledger.jsonl").exists())  # free models: no ledger entry

    def test_health_flags_unparsed_only(self):
        self.run_("smoke")
        _, p_gold = health.check("smoke", "scripted-gold", self.items("check"), self.results / "smoke")
        _, p_bad = health.check("smoke", "scripted-garbage", self.items("check"), self.results / "smoke")
        self.assertEqual(p_gold, [])
        self.assertTrue(any("unparsed" in p for p in p_bad))

    def test_pinned_slug_matches_reported_host(self):
        match = lambda served, pin: health.host_key(served).startswith(health.host_key(pin))
        self.assertTrue(match("Google AI Studio", "google-ai-studio"))
        self.assertTrue(match("Alibaba", "alibaba"))
        self.assertTrue(match("DeepInfra", "deepinfra"))
        self.assertFalse(match("Google", "google-ai-studio"))  # Vertex is a different host

    def test_settings_or_text_change_refuses_to_mix(self):
        self.run_("smoke", "--model", "scripted-gold")
        path = self.results / "smoke" / "scripted-gold.jsonl"
        rows = runner.load_jsonl(path)
        path.write_text("".join(json.dumps({**r, "settings_hash": "other"}) + "\n" for r in rows[:1]))
        with self.assertRaises(SystemExit):
            self.run_("smoke", "--model", "scripted-gold")
        path.write_text("".join(json.dumps({**r, "item_hash": "other"}) + "\n" for r in rows[:1]))
        with self.assertRaises(SystemExit):
            self.run_("smoke", "--model", "scripted-gold")

    def test_frozen_stage_needs_freeze(self):
        with self.assertRaises(SystemExit):
            self.run_("pilot")
        self.assertEqual(self.rows("pilot", "scripted-gold"), [])
        quiet(runner.freeze)  # fingerprints the real protocol files into the temporary FROZEN.json
        self.assertEqual(runner.frozen_problems(), [])
        self.assertEqual(self.run_("pilot"), 0)
        self.assertEqual(len(self.rows("pilot", "scripted-gold")), 216)
        self.assertTrue(self.rows("pilot", "scripted-gold")[0]["provenance"]["frozen"])

    def test_freeze_covers_the_protocol(self):
        quiet(runner.freeze)
        files = json.loads(runner.FROZEN.read_text())["files"]
        for f in ("src/exception_authority/scenarios.py", "src/exception_authority/runner.py", "src/exception_authority/guard.py",
                  "src/exception_authority/scoring.py", "resources/scenarios.jsonl", "resources/config.json", "../PREREG.md"):
            self.assertIn(f, files)

    def test_dry_run_sends_nothing(self):
        self.assertEqual(self.run_("paid", "--dry-run", "--show", "1"), 0)
        self.assertFalse((self.results / "paid").exists() and any((self.results / "paid").iterdir()))

    def test_chat_request_shape(self):
        item = next(i for i in runner.load_jsonl(self.scenarios) if i["cell"] == "C-no")
        cfg = {"provider": "openai_compatible", "model_id": "vendor/model", "temperature": 0,
               "extra_body": {"provider": {"order": ["host/bf16"], "allow_fallbacks": False}}}
        req = runner.build_request(item, cfg)
        self.assertEqual([m["role"] for m in req["messages"]], ["system", "user", "assistant", "tool"])
        self.assertEqual(req["messages"][3]["content"], item["tool_result"])
        self.assertEqual(req["messages"][2]["tool_calls"][0]["id"], req["messages"][3]["tool_call_id"])
        self.assertEqual(req["tool_choice"], "none")
        self.assertEqual(req["response_format"]["json_schema"]["schema"], runner.DECISION_FORMAT["schema"])
        self.assertEqual(runner.pinned_host(cfg), "host")
        self.assertNotEqual(runner.settings_hash(cfg), runner.settings_hash({**cfg, "temperature": 1}))
        self.assertEqual(runner.settings_hash(cfg), runner.settings_hash({**cfg, "price_in": 9.0}))

    def test_anthropic_request_shape(self):
        item = next(i for i in runner.load_jsonl(self.scenarios) if i["cell"] == "D")
        req = runner.build_request(item, {"model_id": "m", "effort": "medium", "max_tokens": 4000})
        self.assertEqual(req["tool_choice"], {"type": "none"})
        self.assertEqual([m["role"] for m in req["messages"]], ["user", "assistant", "user"])
        self.assertEqual(req["messages"][2]["content"][0]["content"], item["tool_result"])
        self.assertEqual(req["output_config"]["effort"], "medium")
        self.assertNotIn("thinking", req)
        req = runner.build_request(item, {"model_id": "m", "effort": "medium", "thinking": "adaptive"})
        self.assertEqual(req["thinking"], {"type": "adaptive"})

    def test_samples_are_separate_units_and_resume(self):
        self.assertEqual(self.run_("sampled"), 0)
        rows = self.rows("sampled", "scripted-gold")
        self.assertEqual(len(rows), 54 * 3)
        self.assertEqual({r["sample"] for r in rows}, {1, 2, 3})
        self.assertEqual(self.run_("sampled"), 0)  # rerun: nothing left to do
        self.assertEqual(len(self.rows("sampled", "scripted-gold")), 54 * 3)

    def test_two_call_protocol(self):
        from exception_authority import scenarios as S
        cfg = json.loads(self.config.read_text())
        cfg["feed_protocol"] = "model_call"
        self.config.write_text(json.dumps(cfg))
        with self.assertRaises(SystemExit):  # scenarios still generated for 'prefill'
            self.run_("twocall")
        with self.scenarios.open("w") as f:
            for it in S.generate("model_call"):
                f.write(json.dumps(it) + "\n")
        it = next(i for i in runner.load_jsonl(self.scenarios) if i["stage"] == "check")
        self.assertIn(S.LOOKUP_SENTENCE, it["system"])
        self.run_("twocall")
        gold = self.rows("twocall", "scripted-gold")
        self.assertEqual(len(gold), 54)
        self.assertTrue(all(r["calls"] == 2 and r["protocol_deviation"] is None and r["parse_ok"] for r in gold))
        self.assertTrue(all(r["decision"] == next(i for i in self.items("check") if i["id"] == r["id"])["gold_decision"]
                            for r in gold))
        skip = self.rows("twocall", "scripted-nolookup")
        self.assertTrue(all(r["calls"] == 1 and r["protocol_deviation"] == "no_lookup" for r in skip))
        # call 2 passes call 1's turn back unchanged and answers each lookup with the fixed entry
        mc = {"model_id": "m", "effort": "medium", "thinking": "adaptive", "feed_protocol": "model_call"}
        first = runner.scripted_response("gold", it, runner.build_lookup_call(it, mc))
        req2 = runner.build_decision_call(it, mc, first)
        self.assertEqual(req2["messages"][1]["content"], first.raw_message)
        self.assertEqual(req2["messages"][2]["content"][0]["content"], it["tool_result"])
        self.assertEqual(req2["tool_choice"], {"type": "none"})
        self.assertNotIn("format", runner.build_lookup_call(it, mc).get("output_config", {}))

    def test_cache_groups_samples_in_order_and_reads_after_write(self):
        self.assertEqual(self.run_("cachedemo", "--limit", "2"), 0)  # --limit counts items: 2 items x 3 samples
        rows = self.rows("cachedemo", "scripted-gold")
        self.assertEqual(len({r["id"] for r in rows}), 2)
        for i in {r["id"] for r in rows}:
            mine = [r for r in rows if r["id"] == i]
            self.assertEqual([r["sample"] for r in mine], [1, 2, 3])  # written in order: k+1 sent after k returned
            self.assertGreater(mine[0]["usage"]["cache_creation_input_tokens"], 0)
            self.assertEqual(mine[0]["usage"]["cache_read_input_tokens"], 0)
            self.assertTrue(all(r["usage"]["cache_read_input_tokens"] > 0 for r in mine[1:]))
            self.assertTrue(all(r["cache_requested"] for r in mine))
        self.assertEqual(self.run_("cachedemo"), 0)  # resume: the remaining items
        out = []
        rc = quiet(lambda: health.main(["cachedemo", "--scenarios", str(self.scenarios),
                                        "--results-dir", str(self.results)]))
        self.assertEqual(rc, 0)

    def test_cache_breakpoint_only_where_the_stage_asks(self):
        it = next(i for i in runner.load_jsonl(self.scenarios) if i["stage"] == "check")
        mc = {"model_id": "m", "effort": "medium", "provider": "anthropic"}
        plain, cached = runner.build_request(it, mc), runner.build_request(it, mc, cache=True)
        self.assertNotIn("cache_control", json.dumps(plain))
        self.assertEqual(cached["messages"][-1]["content"][-1]["cache_control"], {"type": "ephemeral"})
        strip = json.loads(json.dumps(cached))
        strip["messages"][-1]["content"][-1].pop("cache_control")
        self.assertEqual(strip, plain)  # the only difference
        self.assertFalse(runner.caches({"provider": "openai_compatible"}, {"cache": True}))
        self.assertFalse(runner.caches({"provider": "anthropic"}, {}))
        priced = {**mc, "price_in": 4, "price_out": 20, "price_cache_write": 5, "price_cache_read": 0.2}
        self.assertEqual(runner.settings_hash(priced), runner.settings_hash({**mc, "price_in": 1, "price_out": 1}))


if __name__ == "__main__":
    unittest.main()
