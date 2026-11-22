"""Post-hoc template counts (templates.py): verdicts, concentration and discordant pairs."""
import unittest

from exception_authority import templates as T


class TestTemplates(unittest.TestCase):
    def test_verdict_is_a_strict_majority(self):
        self.assertEqual(T.verdict(11, 20), "accept")
        self.assertEqual(T.verdict(9, 20), "refuse")
        self.assertEqual(T.verdict(10, 20), "split")
        self.assertEqual(T.verdict(0, 0), "none")

    def test_concentration_flags_a_single_template(self):
        self.assertEqual(T.concentration({"a": 7, "b": 0}), (7, "a", True))
        self.assertEqual(T.concentration({"a": 2, "b": 4, "c": 0, "d": 20}), (26, "d", True))   # 20/26 >= 3/4
        self.assertEqual(T.concentration({"a": 4, "b": 4, "c": 0, "d": 18}), (26, "d", False))  # 18/26 < 3/4
        self.assertEqual(T.concentration({"a": 0}), (0, None, False))

    def test_discordant_pairs_by_template(self):
        dec = {("b1", "C-ctl"): True, ("b1", "C-no"): False, ("b2", "C-ctl"): True, ("b2", "C-no"): True,
               ("b3", "C-ctl"): False, ("b3", "C-no"): True}
        btpl = {"b1": ("x", "permissive"), "b2": ("x", "permissive"), "b3": ("y", "restrictive")}
        d = T.discordant(dec, btpl, "C-ctl", "C-no")
        self.assertEqual(d[("x", "permissive")], [1, 0])
        self.assertEqual(d[("y", "restrictive")], [0, 1])

    def test_leave_one_template_out(self):
        # template x: two pairs favour C-ctl; template y: one favours C-no, one is concordant
        dec = {("b1", "C-ctl"): True, ("b1", "C-no"): False, ("b2", "C-ctl"): True, ("b2", "C-no"): False,
               ("b3", "C-ctl"): False, ("b3", "C-no"): True, ("b4", "C-ctl"): True, ("b4", "C-no"): True}
        btpl = {"b1": "x", "b2": "x", "b3": "y", "b4": "y"}
        loo = T.leave_one_out(dec, btpl, "C-ctl", "C-no")
        self.assertEqual(loo["x"], (-1, 2))   # only y left: net -1 over 2 pairs
        self.assertEqual(loo["y"], (2, 2))    # only x left: net +2 over 2 pairs

    def test_leave_one_out_skips_pairs_with_an_invalid_cell(self):
        dec = {("b1", "C-ctl"): True, ("b1", "C-no"): False, ("b2", "C-ctl"): True}   # b2 lacks C-no
        loo = T.leave_one_out(dec, {"b1": "x", "b2": "y"}, "C-ctl", "C-no")
        self.assertEqual(loo["y"], (1, 1))
        self.assertEqual(loo["x"], (0, 0))


if __name__ == "__main__":
    unittest.main()
