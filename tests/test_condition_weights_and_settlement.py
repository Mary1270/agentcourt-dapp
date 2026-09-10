import unittest

from ._bootstrap import make_contract


CONDITIONS = [
    {"id": "c1", "name": "on_time", "description": "d", "weight_bps": 3000},
    {"id": "c2", "name": "sources", "description": "d", "weight_bps": 4000},
    {"id": "c3", "name": "quality", "description": "d", "weight_bps": 3000},
]


class TestComputeSettlement(unittest.TestCase):
    def setUp(self):
        self.contract = make_contract()

    def test_all_pass_is_a_valid_full_payment(self):
        results = {"c1": "PASS", "c2": "PASS", "c3": "PASS"}
        finding, passed, failed, unclear, settle = self.contract._compute_settlement(
            CONDITIONS, results
        )
        self.assertEqual(finding, "A_VALID")
        self.assertEqual(passed, 10000)
        self.assertEqual(failed, 0)
        self.assertEqual(unclear, 0)
        self.assertEqual(settle, 10000)

    def test_all_fail_is_b_valid_zero_payment(self):
        results = {"c1": "FAIL", "c2": "FAIL", "c3": "FAIL"}
        finding, passed, failed, unclear, settle = self.contract._compute_settlement(
            CONDITIONS, results
        )
        self.assertEqual(finding, "B_VALID")
        self.assertEqual(settle, 0)

    def test_mixed_result_is_partial_with_weighted_settlement(self):
        # on_time PASS (3000) + sources PASS (4000) + quality FAIL (3000)
        results = {"c1": "PASS", "c2": "PASS", "c3": "FAIL"}
        finding, passed, failed, unclear, settle = self.contract._compute_settlement(
            CONDITIONS, results
        )
        self.assertEqual(finding, "PARTIAL")
        self.assertEqual(passed, 7000)
        self.assertEqual(failed, 3000)
        self.assertEqual(settle, 7000)

    def test_missing_condition_result_defaults_to_unclear(self):
        # c3 omitted entirely -> must default safely to UNCLEAR, not PASS.
        results = {"c1": "PASS", "c2": "PASS"}
        finding, passed, failed, unclear, settle = self.contract._compute_settlement(
            CONDITIONS, results
        )
        self.assertEqual(unclear, 3000)
        self.assertEqual(settle, 7000)

    def test_high_uncertainty_flagged_indeterminate_but_settlement_still_computed(self):
        # unclear weight (7000) exceeds the 3000 threshold -> INDETERMINATE label,
        # but the settlement math is uniform: pay only for weight that PASSED.
        results = {"c1": "PASS", "c2": "UNCLEAR", "c3": "UNCLEAR"}
        finding, passed, failed, unclear, settle = self.contract._compute_settlement(
            CONDITIONS, results
        )
        self.assertEqual(finding, "INDETERMINATE")
        self.assertEqual(unclear, 7000)
        self.assertEqual(settle, 3000)

    def test_a_dissenting_fail_prevents_a_valid_even_at_low_weight(self):
        results = {"c1": "PASS", "c2": "PASS", "c3": "FAIL"}
        finding, *_ = self.contract._compute_settlement(CONDITIONS, results)
        self.assertNotEqual(finding, "A_VALID")


class TestWeightValidationEdgeCases(unittest.TestCase):
    def test_single_condition_full_weight_is_valid(self):
        from ._bootstrap import set_caller, iso_in, PARTY_A_ADDRESS, PARTY_B_ADDRESS

        contract = make_contract()
        set_caller(PARTY_A_ADDRESS)
        agreement_id = contract.create_agreement(
            PARTY_B_ADDRESS, "Task", ["done"], ["Fully delivered."], [10000],
            100, iso_in(7200),
        )
        self.assertTrue(agreement_id)

    def test_zero_or_negative_weight_rejected(self):
        from ._bootstrap import set_caller, iso_in, PARTY_A_ADDRESS, PARTY_B_ADDRESS
        from ._bootstrap import gl

        contract = make_contract()
        set_caller(PARTY_A_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.create_agreement(
                PARTY_B_ADDRESS, "Task", ["a", "b"], ["d1", "d2"], [10000, 0],
                100, iso_in(7200),
            )


if __name__ == "__main__":
    unittest.main()
