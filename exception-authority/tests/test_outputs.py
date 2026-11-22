"""Manuscript outputs: numbers.tex/numbers.md, the tables, valid macro names, and ?? before results."""
import re
import unittest

from exception_authority import outputs, scenarios, scoring

from .support import Harness, quiet


class TestOutputs(Harness):
    def macros(self, stage):
        rows = outputs.collect(stage, self.results, self.scenarios, outputs.config())
        return {m: v for m, v, _, _ in rows}, rows

    def test_before_results_every_result_is_missing(self):
        vals, rows = self.macros("main")
        self.assertEqual(vals["nCells"], "9")
        self.assertEqual(vals["nItemsMain"], "1080")
        self.assertEqual(vals["nModels"], "6")
        self.assertEqual(vals["nVendors"], "5")
        self.assertEqual(vals["priEstOpus"], outputs.MISSING)
        self.assertEqual(vals["ceilingHolds"], outputs.MISSING)
        for name in ("invalidOpus", "applOpus", "faPermOpus", "pairRRctlHaiku", "impOnlyCnoCctlOpus", "flipHaiku", "cacheHitOpus", "checkDifferGptmini", "impPriEstOpus",
                     "impBinBoutHiHaiku", "impFlipOpus"):
            self.assertEqual(vals[name], outputs.MISSING, name)
        tex, md, missing = outputs.write_numbers(rows, self.tmp / "ms")
        self.assertGreater(missing, 0)
        text = tex.read_text()
        self.assertIn(r"\providecommand{\missing}", text)
        for name in re.findall(r"\\newcommand\{\\([^}]*)\}", text):
            self.assertRegex(name, r"^[A-Za-z]+$")
        self.assertEqual(len(set(re.findall(r"\\newcommand\{\\([^}]*)\}", text))), len(rows))  # no duplicates

    def test_after_scoring_results_fill_in(self):
        self.assertEqual(self.run_("fakemain"), 0)
        quiet(scoring.main, ["effects", "fakemain", "--scenarios", str(self.scenarios), "--results-dir", str(self.results)])
        vals, _ = self.macros("fakemain")
        g, a = outputs.model_macro("scripted-gold"), outputs.model_macro("scripted-accept")
        self.assertEqual(vals[f"priEst{g}"], "+100")    # follows the record exactly
        self.assertEqual(vals[f"priEst{a}"], "0")       # accepts everything: no discrimination
        self.assertEqual(vals[f"fa{g}"], "0")
        self.assertEqual(vals[f"fa{a}"], "100")
        self.assertEqual(vals[f"ret{g}"], "100")
        self.assertEqual(vals[f"floorBreak{a}"], "yes")
        self.assertEqual(vals["ceilingHolds"], "no")
        self.assertEqual(vals[f"invalid{g}"], "0")
        self.assertEqual(vals[f"appl{g}"], "0")          # B-out is reported on its own
        self.assertEqual(vals[f"appl{a}"], "100")
        self.assertEqual(vals[f"pairCnoCctl{g}"], "100")  # both members right in every base scenario
        self.assertEqual(vals[f"pairCnoCctl{a}"], "0")
        self.assertEqual(vals[f"faRestr{a}"], "100")
        self.assertEqual(vals[f"retPerm{g}"], "100")
        self.assertEqual(vals[f"impPriEst{g}"], outputs.MISSING)  # the implicit arm is not run yet
        paths = outputs.write_tables("fakemain", self.results, self.scenarios, self.tmp / "tables")
        rates = (self.tmp / "tables" / "rates.tex").read_text()
        self.assertNotIn(outputs.MISSING, rates.split("Implicit-rule arm")[0])  # the implicit arm is not run here
        self.assertEqual(len(paths), 3)  # design, rates (with the implicit block), summary (with the contrasts)
        summary = (self.tmp / "tables" / "summary.tex").read_text()
        self.assertNotIn(outputs.MISSING, summary)
        self.assertIn("(D, R, C-no)", summary)

    def test_clarification_counts_use_the_scorer(self):
        from exception_authority import clarification as CL
        from exception_authority import templates as T
        self.assertEqual(self.run_("fakemain"), 0)
        quiet(scoring.main, ["effects", "fakemain", "--scenarios", str(self.scenarios), "--results-dir", str(self.results)])
        vals, _ = self.macros("fakemain")
        a = outputs.model_macro("scripted-accept")
        scen = T.scenarios_by_id(self.scenarios)
        k = CL.counts(self.results, "fakemain", "scripted-accept", scen)
        self.assertEqual(k["D"]["accepted"], k["D"]["valid"])   # accepts everything
        self.assertGreater(k["D"]["valid"], 0)
        self.assertEqual(vals[f"clarN{a}D"], str(k["D"]["valid"]))
        self.assertEqual(vals[f"clar{a}D"], str(k["D"]["flagged"]))
        self.assertLessEqual(k["D"]["accepted_and_flagged"], min(k["D"]["accepted"], k["D"]["flagged"]))
        written = outputs.write_clarification("fakemain", self.results, self.scenarios, outputs.config())
        self.assertTrue(written)
        lines = written[0].read_text().splitlines()
        self.assertEqual(lines[0], ",".join(CL.COLUMNS))
        self.assertEqual(len(lines) - 1, len(scenarios.CELLS) * len(outputs.config()["stages"]["fakemain"]["models"]))

    def test_implicit_arm_fills_in(self):
        self.assertEqual(self.run_("fakemain"), 0)
        self.assertEqual(self.run_("fakeimplicit"), 0)
        quiet(scoring.main, ["effects", "fakeimplicit", "--scenarios", str(self.scenarios), "--results-dir", str(self.results)])
        vals, _ = self.macros("fakemain")
        g, a = outputs.model_macro("scripted-gold"), outputs.model_macro("scripted-accept")
        self.assertNotEqual(vals[f"impPriEst{g}"], outputs.MISSING)
        self.assertEqual(vals[f"impPriEst{a}"], "0")  # accepts everything in both cells
        outputs.write_tables("fakemain", self.results, self.scenarios, self.tmp / "tables")
        table = (self.tmp / "tables" / "rates.tex").read_text()
        implicit_block = table.split("Implicit-rule arm")[1]
        # cells carry presentation-only shading; the printed values are what this test checks
        implicit_block = re.sub(r"\\textcolor\{white\}\{([^}]*)\}", r"\1", re.sub(r"\\cellcolor\{[^}]*\}", "", implicit_block))
        self.assertNotIn(outputs.MISSING, implicit_block)   # main is not scored in this test; the block is
        self.assertIn("scripted-gold & 0 & 0 & 100 & 0 & 0 & 100 & 100 & 0 & 100", implicit_block)
        self.assertNotEqual(vals[f"impDiffCno{g}"], outputs.MISSING)

    def test_figure(self):
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib not installed")
        self.assertIsNone(quiet(outputs.write_figure, "fakemain", self.results, self.tmp / "fig"))  # no results yet
        self.run_("fakemain")
        quiet(scoring.main, ["effects", "fakemain", "--scenarios", str(self.scenarios), "--results-dir", str(self.results)])
        quiet(scoring.main, ["summary", "fakemain", "--scenarios", str(self.scenarios), "--results-dir", str(self.results)])
        path = outputs.write_figure("fakemain", self.results, self.tmp / "fig")  # reads summary.csv (Wilson intervals)
        self.assertTrue(path.exists() and path.stat().st_size > 1000)

    def test_design_table_quotes_the_stimuli(self):
        table = outputs.design_table(self.scenarios)
        self.assertIn(scenarios.C_RIGHT["C-no"], table)
        self.assertIn("revoked on 1 November 2026", table)
        self.assertIn("reviewed on 1 November 2026", table)
        self.assertNotIn("agents are authorized", table)  # the entry carries no authority claim
        self.assertIn("(no issuer)", table)
        self.assertEqual(table.count(r" \\" + "\n"), len(scenarios.CELLS) + 1)  # header + nine cells


if __name__ == "__main__":
    unittest.main()
