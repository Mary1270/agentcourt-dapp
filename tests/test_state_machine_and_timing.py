import datetime
import unittest

from ._bootstrap import (
    make_contract,
    set_caller,
    iso_in,
    default_conditions,
    create_open_agreement,
    PARTY_A_ADDRESS,
    PARTY_B_ADDRESS,
    STRANGER_ADDRESS,
)
from ._bootstrap import gl


def advance(contract, seconds):
    """Force the contract's notion of "now" forward by `seconds`,
    without touching the real system clock."""
    real_now = contract._now_utc()
    fixed = real_now + datetime.timedelta(seconds=seconds)
    contract._now_utc = lambda: fixed


class TestCreateAgreementValidation(unittest.TestCase):
    def test_party_a_is_the_caller_never_free_text(self):
        contract = make_contract()
        names, descs, weights = default_conditions()
        set_caller(PARTY_A_ADDRESS)
        agreement_id = contract.create_agreement(
            PARTY_B_ADDRESS, "Task", names, descs, weights, 100, iso_in(7200)
        )
        import json

        agreement = json.loads(contract.get_agreement(agreement_id))
        self.assertEqual(agreement["party_a"].lower(), PARTY_A_ADDRESS.lower())
        self.assertEqual(agreement["status"], "pending_acceptance")

    def test_rejects_party_a_equals_party_b(self):
        contract = make_contract()
        names, descs, weights = default_conditions()
        set_caller(PARTY_A_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.create_agreement(
                PARTY_A_ADDRESS, "Task", names, descs, weights, 100, iso_in(7200)
            )

    def test_rejects_weights_not_summing_to_10000(self):
        contract = make_contract()
        set_caller(PARTY_A_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.create_agreement(
                PARTY_B_ADDRESS, "Task", ["a", "b"], ["d1", "d2"], [4000, 4000],
                100, iso_in(7200),
            )

    def test_rejects_duplicate_condition_names(self):
        contract = make_contract()
        set_caller(PARTY_A_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.create_agreement(
                PARTY_B_ADDRESS, "Task", ["same", "same"], ["d1", "d2"],
                [5000, 5000], 100, iso_in(7200),
            )

    def test_rejects_deadline_too_soon(self):
        contract = make_contract()
        names, descs, weights = default_conditions()
        set_caller(PARTY_A_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.create_agreement(
                PARTY_B_ADDRESS, "Task", names, descs, weights, 100, iso_in(10)
            )

    def test_rejects_too_many_conditions(self):
        contract = make_contract()
        set_caller(PARTY_A_ADDRESS)
        names = [f"c{i}" for i in range(9)]
        descs = [f"d{i}" for i in range(9)]
        weights = [10000 // 9] * 9
        with self.assertRaises(gl.vm.UserError):
            contract.create_agreement(
                PARTY_B_ADDRESS, "Task", names, descs, weights, 100, iso_in(7200)
            )


class TestAcceptanceStage(unittest.TestCase):
    def test_only_party_b_can_accept(self):
        contract = make_contract()
        names, descs, weights = default_conditions()
        set_caller(PARTY_A_ADDRESS)
        agreement_id = contract.create_agreement(
            PARTY_B_ADDRESS, "Task", names, descs, weights, 100, iso_in(7200)
        )
        set_caller(STRANGER_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.accept_agreement(agreement_id)
        set_caller(PARTY_A_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.accept_agreement(agreement_id)

    def test_only_party_a_can_cancel_before_acceptance(self):
        contract = make_contract()
        names, descs, weights = default_conditions()
        set_caller(PARTY_A_ADDRESS)
        agreement_id = contract.create_agreement(
            PARTY_B_ADDRESS, "Task", names, descs, weights, 100, iso_in(7200)
        )
        set_caller(PARTY_B_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.cancel_agreement(agreement_id)
        set_caller(PARTY_A_ADDRESS)
        contract.cancel_agreement(agreement_id)
        import json

        agreement = json.loads(contract.get_agreement(agreement_id))
        self.assertEqual(agreement["status"], "cancelled")

    def test_expire_unaccepted_is_permissionless_but_time_gated(self):
        contract = make_contract()
        names, descs, weights = default_conditions()
        set_caller(PARTY_A_ADDRESS)
        agreement_id = contract.create_agreement(
            PARTY_B_ADDRESS, "Task", names, descs, weights, 100, iso_in(7200)
        )
        set_caller(STRANGER_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.expire_unaccepted(agreement_id)

        advance(contract, contract.ACCEPT_WINDOW_SECONDS + 1)
        contract.expire_unaccepted(agreement_id)
        import json

        agreement = json.loads(contract.get_agreement(agreement_id))
        self.assertEqual(agreement["status"], "cancelled")


class TestSubmissionStage(unittest.TestCase):
    def test_only_party_a_can_submit(self):
        contract = make_contract()
        agreement_id = create_open_agreement(contract)
        set_caller(PARTY_B_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.submit_deliverable(agreement_id, "Done.", [])

    def test_submit_after_deadline_rejected_use_expire_instead(self):
        contract = make_contract()
        agreement_id = create_open_agreement(contract, deadline_seconds=4000)
        advance(contract, 4100)
        set_caller(PARTY_A_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.submit_deliverable(agreement_id, "Done.", [])

    def test_expire_unsubmitted_refunds_party_b_in_full(self):
        contract = make_contract()
        agreement_id = create_open_agreement(contract, deadline_seconds=4000)
        advance(contract, 4100)
        set_caller(STRANGER_ADDRESS)
        contract.expire_unsubmitted(agreement_id)
        import json

        agreement = json.loads(contract.get_agreement(agreement_id))
        self.assertEqual(agreement["status"], "refunded")
        self.assertEqual(agreement["verdict_final"]["settlement_to_a_bps"], 0)

    def test_at_most_max_evidence_urls_per_party(self):
        contract = make_contract()
        agreement_id = create_open_agreement(contract)
        set_caller(PARTY_A_ADDRESS)
        too_many = [f"https://example.com/{i}" for i in range(contract.MAX_EVIDENCE_URLS_PER_PARTY + 1)]
        with self.assertRaises(gl.vm.UserError):
            contract.submit_deliverable(agreement_id, "Done.", too_many)

    def test_rejects_non_http_evidence_url(self):
        contract = make_contract()
        agreement_id = create_open_agreement(contract)
        set_caller(PARTY_A_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.submit_deliverable(agreement_id, "Done.", ["ftp://example.com/report"])


class TestDisputeWindowAndUncontestedPath(unittest.TestCase):
    def test_only_party_b_can_dispute_within_window(self):
        contract = make_contract()
        agreement_id = create_open_agreement(contract)
        set_caller(PARTY_A_ADDRESS)
        contract.submit_deliverable(agreement_id, "Done, 6 sources, on time.", [])
        set_caller(PARTY_A_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.raise_dispute(agreement_id, "no", [])

    def test_dispute_after_window_rejected(self):
        contract = make_contract()
        agreement_id = create_open_agreement(contract)
        set_caller(PARTY_A_ADDRESS)
        contract.submit_deliverable(agreement_id, "Done.", [])
        advance(contract, contract.DISPUTE_WINDOW_SECONDS + 1)
        set_caller(PARTY_B_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.raise_dispute(agreement_id, "no", [])

    def test_finalize_uncontested_pays_party_a_in_full(self):
        contract = make_contract()
        agreement_id = create_open_agreement(contract)
        set_caller(PARTY_A_ADDRESS)
        contract.submit_deliverable(agreement_id, "Done.", [])
        advance(contract, contract.DISPUTE_WINDOW_SECONDS + 1)
        set_caller(STRANGER_ADDRESS)
        contract.finalize_uncontested(agreement_id)
        import json

        agreement = json.loads(contract.get_agreement(agreement_id))
        self.assertEqual(agreement["status"], "settled")
        self.assertEqual(agreement["verdict_final"]["settlement_to_a_bps"], 10000)
        self.assertTrue(agreement["verdict_final"]["is_final"])

    def test_get_role_reports_correct_party(self):
        contract = make_contract()
        agreement_id = create_open_agreement(contract)
        self.assertEqual(contract.get_role(agreement_id, PARTY_A_ADDRESS), "party_a")
        self.assertEqual(contract.get_role(agreement_id, PARTY_B_ADDRESS), "party_b")
        self.assertEqual(contract.get_role(agreement_id, STRANGER_ADDRESS), "none")


if __name__ == "__main__":
    unittest.main()
