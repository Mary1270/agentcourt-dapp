import datetime
import json
import unittest
from unittest.mock import patch

from ._bootstrap import (
    make_contract,
    set_caller,
    iso_in,
    create_open_agreement,
    PARTY_A_ADDRESS,
    PARTY_B_ADDRESS,
    STRANGER_ADDRESS,
)
from ._bootstrap import gl


def llm_response(condition_words: dict, confidence="High", summary="ok"):
    lines = [f"CONDITION_{cid}: {word}" for cid, word in condition_words.items()]
    lines.append(f"CONFIDENCE: {confidence}")
    lines.append(f"REASONING_SUMMARY: {summary}")
    return "\n".join(lines)


def advance(contract, seconds):
    real_now = contract._now_utc()
    contract._now_utc = lambda: real_now + datetime.timedelta(seconds=seconds)


def get_agreement(contract, agreement_id):
    return json.loads(contract.get_agreement(agreement_id))


def disputed_agreement(contract, a_urls=None, b_urls=None):
    agreement_id = create_open_agreement(contract)
    set_caller(PARTY_A_ADDRESS)
    contract.submit_deliverable(
        agreement_id, "Delivered 6 sources on time.", a_urls or ["https://example.com/report"]
    )
    set_caller(PARTY_B_ADDRESS)
    contract.raise_dispute(
        agreement_id, "Only 3 sources qualify.", b_urls or ["https://example.com/count"]
    )
    return agreement_id


class TestResolveDisputeAndEvidenceLock(unittest.TestCase):
    @patch.object(gl.nondet.web, "render", return_value="some page content here that is long enough")
    @patch.object(gl.nondet, "exec_prompt")
    def test_all_pass_produces_a_valid_full_payment(self, mock_prompt, mock_render):
        contract = make_contract()
        agreement_id = disputed_agreement(contract)
        mock_prompt.return_value = llm_response(
            {"c1": "PASS", "c2": "PASS", "c3": "PASS"}
        )
        set_caller(STRANGER_ADDRESS)
        contract.resolve_dispute(agreement_id)
        agreement = get_agreement(contract, agreement_id)
        self.assertEqual(agreement["status"], "adjudicated")
        self.assertEqual(agreement["verdict_1"]["finding"], "A_VALID")
        self.assertEqual(agreement["verdict_1"]["settlement_to_a_bps"], 10000)

    @patch.object(gl.nondet.web, "render", return_value="page content, long enough to be classified ok")
    @patch.object(gl.nondet, "exec_prompt")
    def test_evidence_set_is_the_union_of_both_parties_committed_urls(self, mock_prompt, mock_render):
        contract = make_contract()
        agreement_id = disputed_agreement(
            contract,
            a_urls=["https://a.example.com/report"],
            b_urls=["https://b.example.com/count"],
        )
        mock_prompt.return_value = llm_response({"c1": "PASS", "c2": "FAIL", "c3": "PASS"})
        set_caller(STRANGER_ADDRESS)
        contract.resolve_dispute(agreement_id)
        agreement = get_agreement(contract, agreement_id)
        locked = set(agreement["locked_evidence_urls"])
        self.assertEqual(
            locked, {"https://a.example.com/report", "https://b.example.com/count"}
        )
        # A later call cannot exist (resolve_dispute is one-shot per
        # status transition) - the lock is therefore immutable by
        # construction, not just by a re-check.
        with self.assertRaises(gl.vm.UserError):
            contract.resolve_dispute(agreement_id)

    @patch.object(gl.nondet.web, "render", side_effect=Exception("network down"))
    @patch.object(gl.nondet, "exec_prompt")
    def test_unreachable_evidence_still_produces_a_verdict_via_unclear(self, mock_prompt, mock_render):
        contract = make_contract()
        agreement_id = disputed_agreement(contract)
        # Model can't verify sources without evidence -> UNCLEAR on that condition.
        mock_prompt.return_value = llm_response(
            {"c1": "PASS", "c2": "UNCLEAR", "c3": "PASS"}
        )
        set_caller(STRANGER_ADDRESS)
        contract.resolve_dispute(agreement_id)
        agreement = get_agreement(contract, agreement_id)
        evidence = agreement["verdict_1"]["evidence"]
        self.assertTrue(all(e["fetch_status"] == "inaccessible" for e in evidence))
        self.assertEqual(agreement["verdict_1"]["settlement_to_a_bps"], 6000)

    @patch.object(gl.nondet.web, "render", return_value="content long enough to pass classification checks")
    @patch.object(gl.nondet, "exec_prompt")
    def test_force_timeout_dispute_refunds_after_window(self, mock_prompt, mock_render):
        contract = make_contract()
        agreement_id = disputed_agreement(contract)
        set_caller(STRANGER_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.force_timeout_dispute(agreement_id)
        advance(contract, contract.MAX_ADJUDICATION_WINDOW_SECONDS + 1)
        contract.force_timeout_dispute(agreement_id)
        agreement = get_agreement(contract, agreement_id)
        self.assertEqual(agreement["status"], "refunded")
        self.assertEqual(agreement["verdict_final"]["settlement_to_a_bps"], 0)


class TestAppealEligibilityAndResolution(unittest.TestCase):
    def _adjudicate(self, contract, agreement_id, condition_words):
        with patch.object(gl.nondet.web, "render", return_value="content long enough to classify ok"), \
             patch.object(gl.nondet, "exec_prompt", return_value=llm_response(condition_words)):
            set_caller(STRANGER_ADDRESS)
            contract.resolve_dispute(agreement_id)

    def test_full_winner_cannot_appeal_their_own_win(self):
        contract = make_contract()
        agreement_id = disputed_agreement(contract)
        self._adjudicate(contract, agreement_id, {"c1": "PASS", "c2": "PASS", "c3": "PASS"})
        set_caller(PARTY_A_ADDRESS)  # party_a fully won (A_VALID)
        with self.assertRaises(gl.vm.UserError):
            contract.raise_appeal(agreement_id, "I still want to appeal even though I won.")

    def test_losing_party_can_appeal_a_full_loss(self):
        contract = make_contract()
        agreement_id = disputed_agreement(contract)
        self._adjudicate(contract, agreement_id, {"c1": "FAIL", "c2": "FAIL", "c3": "FAIL"})
        set_caller(PARTY_A_ADDRESS)  # party_a fully lost (B_VALID) -> may appeal
        contract.raise_appeal(agreement_id, "The sources were miscounted.")
        agreement = get_agreement(contract, agreement_id)
        self.assertEqual(agreement["status"], "appealed")
        self.assertEqual(agreement["appeal"]["appellant"], "party_a")

    def test_either_party_can_appeal_a_partial_verdict(self):
        contract = make_contract()
        agreement_id = disputed_agreement(contract)
        self._adjudicate(contract, agreement_id, {"c1": "PASS", "c2": "FAIL", "c3": "PASS"})
        set_caller(PARTY_B_ADDRESS)
        contract.raise_appeal(agreement_id, "Even the passing conditions were not fully met.")
        agreement = get_agreement(contract, agreement_id)
        self.assertEqual(agreement["status"], "appealed")

    def test_appeal_after_challenge_window_rejected(self):
        contract = make_contract()
        agreement_id = disputed_agreement(contract)
        self._adjudicate(contract, agreement_id, {"c1": "FAIL", "c2": "FAIL", "c3": "FAIL"})
        advance(contract, contract.CHALLENGE_WINDOW_SECONDS + 1)
        set_caller(PARTY_A_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.raise_appeal(agreement_id, "Too late but trying anyway.")

    def test_finalize_unappealed_locks_in_first_verdict(self):
        contract = make_contract()
        agreement_id = disputed_agreement(contract)
        self._adjudicate(contract, agreement_id, {"c1": "PASS", "c2": "PASS", "c3": "PASS"})
        advance(contract, contract.CHALLENGE_WINDOW_SECONDS + 1)
        set_caller(STRANGER_ADDRESS)
        contract.finalize_unappealed(agreement_id)
        agreement = get_agreement(contract, agreement_id)
        self.assertEqual(agreement["status"], "settled")
        self.assertTrue(agreement["verdict_final"]["is_final"])
        self.assertEqual(agreement["verdict_final"]["finding"], "A_VALID")

    @patch.object(gl.nondet.web, "render", return_value="content long enough to classify ok")
    @patch.object(gl.nondet, "exec_prompt")
    def test_resolve_appeal_can_overturn_the_first_verdict_and_is_final(self, mock_prompt, mock_render):
        contract = make_contract()
        agreement_id = disputed_agreement(contract)
        mock_prompt.return_value = llm_response({"c1": "FAIL", "c2": "FAIL", "c3": "FAIL"})
        set_caller(STRANGER_ADDRESS)
        contract.resolve_dispute(agreement_id)

        set_caller(PARTY_A_ADDRESS)
        contract.raise_appeal(agreement_id, "Re-examine: the sources DO qualify.")

        # Second round: the appeal argument persuades the adjudicator.
        mock_prompt.return_value = llm_response({"c1": "PASS", "c2": "PASS", "c3": "PASS"})
        set_caller(STRANGER_ADDRESS)
        contract.resolve_appeal(agreement_id)

        agreement = get_agreement(contract, agreement_id)
        self.assertEqual(agreement["status"], "settled")
        self.assertEqual(agreement["verdict_final"]["finding"], "A_VALID")
        self.assertTrue(agreement["verdict_final"]["is_final"])
        self.assertEqual(agreement["verdict_final"]["reason"], "appeal_resolved")

        # No second appeal is possible - state machine has no
        # 'appealed' -> 'adjudicated' transition.
        set_caller(PARTY_B_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.raise_appeal(agreement_id, "I want another round.")

    def test_appeal_evidence_cannot_be_expanded(self):
        """The appeal call itself takes no URL argument at all - this
        test documents that guarantee at the API level."""
        contract = make_contract()
        self.assertNotIn("evidence_urls", contract.raise_appeal.__code__.co_varnames)

    @patch.object(gl.nondet.web, "render", return_value="content long enough to classify ok")
    @patch.object(gl.nondet, "exec_prompt")
    def test_force_timeout_appeal_falls_back_to_first_verdict(self, mock_prompt, mock_render):
        contract = make_contract()
        agreement_id = disputed_agreement(contract)
        mock_prompt.return_value = llm_response({"c1": "PASS", "c2": "FAIL", "c3": "PASS"})
        set_caller(STRANGER_ADDRESS)
        contract.resolve_dispute(agreement_id)
        set_caller(PARTY_B_ADDRESS)
        contract.raise_appeal(agreement_id, "Not satisfied with the partial result.")

        set_caller(STRANGER_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            contract.force_timeout_appeal(agreement_id)
        advance(contract, contract.MAX_ADJUDICATION_WINDOW_SECONDS + 1)
        contract.force_timeout_appeal(agreement_id)

        agreement = get_agreement(contract, agreement_id)
        self.assertEqual(agreement["status"], "settled")
        self.assertEqual(agreement["verdict_final"]["settlement_to_a_bps"], 6000)
        self.assertEqual(
            agreement["verdict_final"]["reason"], "appeal_timed_out_fell_back_to_first_verdict"
        )


if __name__ == "__main__":
    unittest.main()
