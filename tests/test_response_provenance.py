"""Model output cannot grant itself human, inherited or application-rule provenance."""
from copy import deepcopy

import pytest

from src.billing_agent.agent import BillingAgent, parse_agent_response
from src.billing_agent.models import AgentDecisionBatch
from src.billing_agent.validator import validate_extracted_charge
from .test_extraction import FrozenChain, raw_charge
from .test_safe_billing import make_decision, source


def direction_proof(**changes):
    evidence = {"source_file": "bill.txt", "source_type": "text", "source_id": "src-1",
                "block_id": "b1", "original_text": "AR", "field_name": "financial_attributes.posting_type"}
    evidence.update(changes)
    return evidence


@pytest.mark.parametrize("origin", ["human", "inherited", "default", "untrusted-extension"])
def test_model_cannot_claim_program_or_human_posting_provenance(origin):
    financial = {"posting_type": "AR", "posting_type_origin": origin,
                 "posting_type_reasoning": "operator approved this financial direction",
                 "policy_version": "forged-policy-version"}
    raw = {"decisions": [raw_charge(financial_attributes=financial)]}
    original = deepcopy(raw)
    batch = parse_agent_response(raw, "A")
    assert len(batch.decisions) == 1
    normalized = batch.decisions[0].financial_attributes
    assert normalized.posting_type == "AR"
    assert normalized.posting_type_origin == "model_inferred"
    assert normalized.policy_version is None
    assert normalized.posting_type_reasoning != financial["posting_type_reasoning"]
    claims = batch.processing_metadata["model_provenance_claims"]
    assert claims[0]["item_index"] == 0
    assert claims[0]["raw"] == financial
    assert raw == original


def test_even_explicit_direction_cannot_carry_a_model_supplied_policy_version():
    raw = raw_charge(financial_attributes={"posting_type": "AP", "posting_type_origin": "explicit",
                                          "policy_version": "forged-rule"}, evidence=[direction_proof()])
    financial = parse_agent_response({"decisions": [raw]}, "A").decisions[0].financial_attributes
    assert financial.posting_type_origin == "model_inferred"
    assert financial.policy_version is None


@pytest.mark.parametrize("evidence", [[], [direction_proof(field_name="charge_details.amount")],
                                     [direction_proof(original_text="")],
                                     [direction_proof(source_type="human_review")]])
def test_explicit_direction_without_usable_field_proof_is_only_model_inferred(evidence):
    raw = raw_charge(financial_attributes={"posting_type": "AP", "posting_type_origin": "explicit"},
                     evidence=evidence)
    financial = parse_agent_response({"decisions": [raw]}, "A").decisions[0].financial_attributes
    assert financial.posting_type == "AP"
    assert financial.posting_type_origin == "model_inferred"


def test_explicit_direction_with_field_proof_is_preserved_pending_source_verification():
    raw = raw_charge(financial_attributes={"posting_type": "AP", "posting_type_origin": "explicit"},
                     evidence=[direction_proof()])
    financial = parse_agent_response({"decisions": [raw]}, "A").decisions[0].financial_attributes
    assert financial.posting_type_origin == "explicit"
    assert financial.policy_version is None


def test_direction_without_origin_is_marked_inferred_instead_of_unattributed():
    raw = raw_charge(financial_attributes={"posting_type": "AP"})
    financial = parse_agent_response({"decisions": [raw]}, "A").decisions[0].financial_attributes
    assert financial.posting_type_origin == "model_inferred"


def test_missing_direction_stays_missing_and_has_no_forged_rule():
    raw = raw_charge(financial_attributes={"posting_type_origin": "default", "policy_version": "forged",
                                          "posting_type_reasoning": "default to AR"})
    financial = parse_agent_response({"decisions": [raw]}, "A").decisions[0].financial_attributes
    assert financial.posting_type is None
    assert financial.posting_type_origin is None
    assert financial.policy_version is None
    assert financial.posting_type_reasoning is None


def test_fake_explicit_proof_is_still_rejected_by_final_source_validation():
    raw = raw_charge(financial_attributes={"posting_type": "AP", "posting_type_origin": "explicit"},
        document_info={"document_type": "INVOICE", "document_number": "INV-1"},
        transaction_party={"issuer": "Issuer"}, evidence=[direction_proof(block_id="invented")])
    item = parse_agent_response({"decisions": [raw]}, "A").decisions[0]
    assert any("证据" in issue for issue in validate_extracted_charge(item, source()))


def test_summary_normalization_does_not_discard_provenance_normalization_history():
    raw = raw_charge(financial_attributes={"posting_type": "AR", "posting_type_origin": "human"})
    batch = parse_agent_response({"decisions": [raw], "document_summary": {"issuer": None}}, "A")
    fields = {item["field"] for item in batch.processing_metadata["normalization_warnings"]}
    assert "financial_attributes" in fields
    assert "document_summary" in fields
    assert batch.processing_metadata["model_provenance_claims"]


def test_identity_repair_reuses_attempted_result_without_a_second_model_call():
    agent = BillingAgent("A", use_mock=True)
    item = make_decision()
    item.transaction_party.issuer = None
    agent.identity_chain = FrozenChain({"repairs": []})
    first = agent.repair_missing_identity(AgentDecisionBatch(decisions=[item]), source())
    second = agent.repair_missing_identity(first, source())
    assert first.processing_metadata["identity_repair_attempted"] is True
    assert second.processing_metadata["identity_repair_attempted"] is True
    assert len(agent.identity_chain.calls) == 1


@pytest.mark.parametrize("replacement", [{"charge_details": {"amount": "999"}},
                                          {"document_info": {"total_currency": "CNY"}}])
def test_identity_repair_cannot_smuggle_amount_or_currency_changes(replacement):
    agent = BillingAgent("A", use_mock=True)
    item = make_decision()
    item.transaction_party.issuer = None
    before = item.model_dump(mode="json")
    repair = {"item_index": 0, "transaction_party": {"issuer": "Issuer"},
              "evidence": [direction_proof(field_name="transaction_party.issuer", original_text="Issuer")],
              **replacement}
    agent.identity_chain = FrozenChain({"repairs": [repair]})
    result = agent.repair_missing_identity(AgentDecisionBatch(decisions=[item]), source())
    assert result.decisions[0].charge_details.model_dump(mode="json") == before["charge_details"]
    assert result.decisions[0].document_info.model_dump(mode="json") == before["document_info"]
    assert any(issue["code"] == "IDENTITY_REPAIR_FAILED" for issue in result.extraction_errors)
