"""Shared fixture: a temporary copy of the config with extra scripted models and test stages, freshly
generated scenarios, and the runner pointed at them. Nothing touches results/ or FROZEN.json."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from exception_authority import paths, runner, scenarios


def quiet(fn, *args):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args)


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.results = self.tmp / "results"
        cfg = json.loads(paths.CONFIG.read_text())
        m, st = cfg["models"], cfg["stages"]
        m["scripted-fatal"] = {"provider": "scripted", "policy": "fatal"}
        m["scripted-flaky"] = {"provider": "scripted", "policy": "flaky"}
        m["scripted-nolookup"] = {"provider": "scripted", "policy": "nolookup"}
        m["router-unpriced"] = {"provider": "openai_compatible", "model_id": "vendor/model",
                                "base_url": "https://openrouter.ai/api/v1"}
        st["router"] = {"scenarios": "check", "models": ["router-unpriced"], "frozen": False, "purpose": "test"}
        st["pilot"] = {"scenarios": "pilot", "models": ["scripted-gold"], "frozen": True, "purpose": "test"}
        st["paid"] = {"scenarios": "pilot", "models": ["scripted-paid"], "frozen": False, "purpose": "test"}
        st["bad"] = {"scenarios": "check", "models": ["scripted-fatal", "scripted-flaky"], "frozen": False, "purpose": "test"}
        st["fakemain"] = {"scenarios": "main", "models": ["scripted-gold", "scripted-accept"], "frozen": False, "purpose": "test"}
        st["sampled"] = {"scenarios": "check", "models": ["scripted-gold"], "frozen": False, "purpose": "test",
                         "samples": {"scripted-gold": 3}}
        st["cachedemo"] = {"scenarios": "check", "models": ["scripted-gold"], "frozen": False, "purpose": "test",
                           "cache": True, "samples": {"scripted-gold": 3}}
        st["twocall"] = {"scenarios": "check", "models": ["scripted-gold", "scripted-nolookup"], "frozen": False,
                         "purpose": "test"}
        st["fakepanel"] = {"scenarios": "main", "models": ["scripted-gold", "scripted-accept", "scripted-never"],
                           "outside_panel": ["scripted-never"], "frozen": False, "purpose": "test"}
        st["fakeimplicit"] = {"scenarios": "main-implicit", "models": ["scripted-gold", "scripted-accept"],
                              "frozen": False, "exploratory": True, "pairs_with": "fakemain", "purpose": "test"}
        self.config = self.tmp / "config.json"
        self.config.write_text(json.dumps(cfg))
        self.scenarios = self.tmp / "scenarios.jsonl"
        quiet(scenarios.main, ["--out", str(self.scenarios)])
        self._saved = (runner.CONFIG, runner.FROZEN)
        runner.CONFIG, runner.FROZEN = self.config, self.tmp / "FROZEN.json"

    def tearDown(self):
        runner.CONFIG, runner.FROZEN = self._saved

    def run_(self, *argv) -> int:
        return quiet(runner.main, [*argv, "--scenarios", str(self.scenarios), "--results-dir", str(self.results)])

    def rows(self, stage, model):
        return runner.load_jsonl(self.results / stage / f"{model}.jsonl")

    def items(self, stage):
        return [i for i in runner.load_jsonl(self.scenarios) if i["stage"] == stage]
