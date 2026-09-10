"""
Shared test bootstrap - wires up the offline genlayer SDK stub and
loads contract.py once.
"""
import importlib.util
import os
import sys
import datetime

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_STUB_DIR = os.path.join(_THIS_DIR, "genlayer_stub")
if _STUB_DIR not in sys.path:
    sys.path.insert(0, _STUB_DIR)

_CONTRACT_PATH = os.path.join(os.path.dirname(_THIS_DIR), "contract.py")
_spec = importlib.util.spec_from_file_location("agentcourt_contract", _CONTRACT_PATH)
_contract_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract_module)

AgentCourt = _contract_module.AgentCourt
gl = _contract_module.gl
Address = _contract_module.Address


def make_contract() -> "AgentCourt":
    return AgentCourt()


PARTY_A_ADDRESS = "0x" + "11" * 20
PARTY_B_ADDRESS = "0x" + "22" * 20
STRANGER_ADDRESS = "0x" + "33" * 20


def set_caller(address_str: str):
    """Simulate a specific wallet calling the next contract method."""
    gl.message.sender_address = Address(address_str)


def iso_in(seconds: float) -> str:
    """Convenience: an ISO-8601 UTC timestamp `seconds` from now."""
    return (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(seconds=seconds)
    ).isoformat()


def default_conditions():
    """A standard 3-condition contract summing to 10000 bps, used
    across most tests: on-time delivery, source count, and quality."""
    names = ["on_time", "min_sources", "quality"]
    descs = [
        "Report was delivered before the agreed deadline.",
        "Report cites at least 5 qualifying, distinct sources.",
        "Report content directly addresses the requested market topic.",
    ]
    weights = [3000, 4000, 3000]
    return names, descs, weights


def create_open_agreement(contract, deadline_seconds=7200, payment_amount=100):
    """Helper: create + accept an agreement, leaving it in 'open'
    status, ready for submit_deliverable. Returns the agreement_id."""
    names, descs, weights = default_conditions()
    set_caller(PARTY_A_ADDRESS)
    agreement_id = contract.create_agreement(
        PARTY_B_ADDRESS,
        "Prepare a market research report.",
        names,
        descs,
        weights,
        payment_amount,
        iso_in(deadline_seconds),
    )
    set_caller(PARTY_B_ADDRESS)
    contract.accept_agreement(agreement_id)
    return agreement_id
