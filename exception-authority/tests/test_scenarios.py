import unittest

from exception_authority import derive as D
from exception_authority import scenarios as S

from .support import quiet


class TestScenarios(unittest.TestCase):
    def test_selftest(self):
        quiet(S.selftest)  # counts, minimal pairs, shared sentences, balance, gold labels

    def test_gold_follows_the_record(self):
        items = S.generate()
        for it in items:
            self.assertEqual(it["derivable"], it["cell"] in S.DERIVABLE)
            self.assertEqual(it["gold_decision"] == it["exception_decision"], it["derivable"])

    def test_every_prompt_states_authenticity_and_closed_world(self):
        for it in S.generate():
            self.assertIn("Policy feed entries are authenticated", it["system"])
            self.assertIn("Authentication covers only these facts.", it["system"])
            self.assertNotIn("delegator", it["system"])  # no cue that names what one cell tests
            self.assertEqual("An exception applies only if its issuer holds the power" in it["system"],
                             it["arm"] == "explicit")
            self.assertIn("is a company employee", it["system"])
            self.assertNotIn("verified", it["system"])  # "verified delegation" could be read as "valid"
            self.assertNotIn("authorized", it["tool_result"])  # an unattributed authority claim


    def test_implicit_arm_only_deletes_the_closed_world_sentence(self):
        items = S.generate()
        by = {i["id"]: i for i in items}
        implicit = [i for i in items if i["arm"] == "implicit"]
        self.assertEqual(len(implicit), 54 + 1080)
        self.assertFalse({i["stage"] for i in implicit} & set(S.STAGES))  # no explicit stage can load them
        for it in implicit:
            twin = by[it["id"].removesuffix("-implicit")]
            self.assertEqual(it["system"], twin["system"].replace(S.CLOSED_WORLD, ""))
            self.assertEqual((it["tool_result"], it["user"], it["base"]), (twin["tool_result"], twin["user"], twin["base"]))


class TestDerive(unittest.TestCase):
    """derive.py recomputes gold from the text, so a changed record must change its answer."""

    def setUp(self):
        self.c = {it["cell"]: it for it in S.generate() if it["base"] == "refunds-permissive-v0"}

    def test_agrees_with_every_gold_label(self):
        self.assertEqual(D.mismatches(S.generate()), [])

    def test_record_edits_flip_the_answer(self):
        def flipped(cell, old, new, field="system"):
            it = dict(self.c[cell])
            self.assertIn(old, it[field])
            it[field] = it[field].replace(old, new)
            return D.derive(it)

        self.assertEqual(D.derive(self.c["C-no"]), "deny")
        self.assertEqual(flipped("C-no", "but may not delegate", "and may delegate"), "approve")
        self.assertEqual(flipped("C-ok", "and may delegate", "but may not delegate"), "deny")
        self.assertEqual(flipped("R-ctl", "reviewed", "revoked"), "deny")
        # revoked after the entry was issued: the prompts never say whether such an exception
        # survives, so the encoding refuses instead of choosing a semantics
        with self.assertRaises(D.Undefined):
            flipped("R", "revoked on 1 November", "revoked on 12 November")
        # the contractor qualifier bars the delegation once the issuer is no longer an employee
        self.assertEqual(flipped("C-ctl", "is a company employee", "is an external contractor"), "deny")
        # D gains the power only when the record grants it
        self.assertEqual(D.derive(self.c["D"]), "deny")
        self.assertEqual(D.derive(self.c["B-in"]), "approve")
        self.assertEqual(D.derive(self.c["B-out"]), "deny")


if __name__ == "__main__":
    unittest.main()
