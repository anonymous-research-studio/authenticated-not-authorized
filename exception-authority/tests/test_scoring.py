import json
import unittest

from exception_authority import scoring

from .support import Harness, quiet


class TestScoringUnits(unittest.TestCase):
    def test_selftest(self):
        quiet(scoring.selftest)  # go/no-go (P1 per cell, D never read), contrasts, Holm, outcomes F and C

    def test_mcnemar_examples_in_prereg(self):
        self.assertAlmostEqual(scoring.mcnemar_exact(15, 3), 0.00754, places=5)
        self.assertAlmostEqual(scoring.mcnemar_exact(10, 0), 2 / 1024, places=12)


class TestScoringFiles(Harness):
    def test_effects_and_gonogo_are_written(self):
        self.assertEqual(self.run_("fakemain"), 0)
        rc = quiet(scoring.main, ["effects", "fakemain", "--scenarios", str(self.scenarios),
                                  "--results-dir", str(self.results)])
        self.assertEqual(rc, 0)
        eff = json.loads((self.results / "fakemain" / "effects.json").read_text())
        self.assertEqual(set(eff["models"]), {"scripted-gold", "scripted-accept"})
        self.assertFalse(eff["outcomes"]["floor_break"]["scripted-gold"])
        self.assertTrue(eff["outcomes"]["floor_break"]["scripted-accept"])
        self.assertIn("family", eff["models"]["scripted-gold"]["contrasts"]["C-ctl - C-no"])
        self.run_("pilot", "--dry-run")  # frozen stage: dry run only warns

    def test_panel_excludes_unlisted_configurations(self):
        self.assertEqual(self.run_("fakemain"), 0)
        self.assertEqual(self.run_("fakemain", "--model", "scripted-never"), 0)  # not in the stage's list
        args = ["--scenarios", str(self.scenarios), "--results-dir", str(self.results)]
        self.assertEqual(quiet(scoring.main, ["effects", "fakemain", *args]), 0)
        eff = json.loads((self.results / "fakemain" / "effects.json").read_text())
        self.assertEqual(eff["outside_panel"], ["scripted-never"])
        self.assertNotIn("scripted-never", eff["outcomes"]["floor_break"])
        self.assertNotIn("holm_p", eff["models"]["scripted-never"]["contrasts"]["C-ctl - C-no"])

    def test_outside_panel_runs_but_stays_out_of_holm_and_f(self):
        self.assertEqual(self.run_("fakepanel"), 0)  # all three run, as listed
        args = ["--scenarios", str(self.scenarios), "--results-dir", str(self.results)]
        self.assertEqual(quiet(scoring.main, ["effects", "fakepanel", *args]), 0)
        eff = json.loads((self.results / "fakepanel" / "effects.json").read_text())
        self.assertEqual(eff["panel"], ["scripted-accept", "scripted-gold"])
        self.assertEqual(eff["outside_panel"], ["scripted-never"])
        self.assertNotIn("scripted-never", eff["outcomes"]["floor_break"])
        self.assertNotIn("holm_p", eff["models"]["scripted-never"]["contrasts"]["C-ctl - C-no"])
        self.assertIn("holm_p", eff["models"]["scripted-gold"]["contrasts"]["C-ctl - C-no"])

    def test_deviation_is_invalid_and_reliability_counts_flips(self):
        self.assertFalse(scoring.valid({"parse_ok": True, "stop_reason": "end_turn", "protocol_deviation": "no_lookup"}))
        scen = {"x": {"cell": "C-no"}}
        rows = [{"id": "x", "sample": k, "decision": d, "parse_ok": True, "stop_reason": "end_turn"}
                for k, d in ((1, "deny"), (2, "approve"), (3, "deny"))]
        rel = scoring.reliability(rows, scen)
        self.assertEqual((rel["items"], rel["flip_rate"]), (1, 1.0))

    def test_implicit_arm_is_scored_without_labels(self):
        self.assertEqual(self.run_("fakemain"), 0)
        self.assertEqual(self.run_("fakeimplicit"), 0)
        args = ["--scenarios", str(self.scenarios), "--results-dir", str(self.results)]
        self.assertEqual(quiet(scoring.main, ["effects", "fakeimplicit", *args]), 0)
        eff = json.loads((self.results / "fakeimplicit" / "effects.json").read_text())
        self.assertTrue(eff["exploratory"])
        self.assertNotIn("outcomes", eff)  # no F, no C
        res = eff["models"]["scripted-accept"]
        self.assertEqual(set(res["contrasts"]), set(scoring.IMPLICIT_CONTRASTS))  # no Holm family
        self.assertNotIn(scoring.FALSE_KEY, res)
        diff = res["explicit_minus_implicit"]["C-no"]
        self.assertEqual((diff["n"], diff["estimate"][0]), (120, 0.0))  # same policy in both arms
        with self.assertRaises(SystemExit):
            quiet(scoring.main, ["gonogo", "fakeimplicit", *args])
        quiet(self.run_, "smoke")


if __name__ == "__main__":
    unittest.main()
