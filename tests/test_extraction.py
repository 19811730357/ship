"""Extraction and candidate proposals must preserve facts and uncertainty."""

from copy import deepcopy
from decimal import Decimal
import json

from src.billing_agent.agent import BillingAgent, parse_agent_response
from src.billing_agent.models import (
    ChargeDetails, DocumentInfo, Evidence, FinancialAttributes, Ledger, LedgerRecord,
    TransactionParty,
)
from src.billing_agent.validator import CHARGE_NAME_MAPPING


def test_original_and_settlement_values_keep_explicit_exchange_rate():
    charge = ChargeDetails(original_name="WHARFAGE", amount="21.90", currency="USD",
                           settlement_amount="21.90", settlement_currency="USD", exchange_rate="1.0000")
    assert charge.exchange_rate == Decimal("1.0000")


def raw_charge(amount="35.00", **changes):
    data = {
        "charge_details": {"original_name": "HANDLING CHARGE", "amount": amount,
                           "currency": "USD", "source_line_id": "source-1:row-3"},
        "document_info": {"document_number": "TEST-INVOICE"},
        "transaction_party": {},
        "financial_attributes": {},
    }
    data.update(changes)
    return data


def test_zero_is_a_fact_and_missing_evidence_is_not_manufactured():
    raw = {"decisions": [raw_charge(0)]}
    original = deepcopy(raw)
    batch = parse_agent_response(raw, "Book A")
    assert len(batch.decisions) == 1
    decision = batch.decisions[0]
    assert decision.charge_details.amount == Decimal("0")
    assert decision.evidence == []
    assert decision.confidence == "LOW"
    assert not decision.revision_requested
    assert raw == original


def test_bad_entries_are_reported_without_silently_losing_rows():
    invalid = raw_charge(None)
    batch = parse_agent_response({"decisions": [raw_charge(), invalid, "bad row"]}, "Book A")
    assert len(batch.decisions) == 1
    assert len(batch.extraction_errors) == 2
    assert batch.extraction_errors[0]["raw"] == invalid
    assert batch.extraction_errors[0]["item_index"] == 1
    assert batch.processing_metadata["input_decisions_count"] == 3


def test_equal_names_remain_distinct_lines_with_typed_document_amounts():
    first, second = raw_charge("65.00"), raw_charge("35.00")
    first["charge_details"]["source_line_id"] = "source-1:row-1"
    for row in (first, second):
        row["document_info"].update({
            "master_bill_of_lading": "MBL-1", "house_bill_of_lading": "HBL-1",
            "container_numbers": ["BOX-1", "BOX-2"], "document_total": "100.00",
            "total_currency": "USD", "paid_amount": "20.00", "balance_due": "80.00",
        })
    batch = parse_agent_response({"decisions": [first, second]}, "Book A")
    assert len(batch.decisions) == 2
    assert batch.decisions[0].charge_details.source_line_id != batch.decisions[1].charge_details.source_line_id
    info = batch.decisions[0].document_info
    assert info.document_total == Decimal("100.00")
    assert info.paid_amount == Decimal("20.00")
    assert info.balance_due == Decimal("80.00")
    assert info.master_bill_of_lading == "MBL-1"
    assert info.house_bill_of_lading == "HBL-1"
    assert info.container_numbers == ["BOX-1", "BOX-2"]


def test_original_and_settlement_amounts_are_separate_and_unknown_currency_is_null():
    row = raw_charge("12.345678")
    row["charge_details"].update({"currency": None, "settlement_amount": "90.123456",
                                  "settlement_currency": "CNY", "amount_role": "line_amount"})
    batch = parse_agent_response({"decisions": [row]}, "Book A")
    charge = batch.decisions[0].charge_details
    assert charge.currency is None
    assert charge.amount == Decimal("12.345678")
    assert charge.settlement_amount == Decimal("90.123456")
    assert charge.settlement_currency == "CNY"


def test_field_evidence_survives_roundtrip_and_is_saved_on_records():
    evidence = Evidence(source_file="bill.pdf", source_type="pdf", original_text="35.00",
                        source_id="source-1", block_id="p1:r3:c5", page=1, row=3,
                        column=5, field_name="charge_details.amount")
    record = LedgerRecord(charge_details=ChargeDetails(original_name="HANDLING", amount="35", currency="USD"),
                          document_info=DocumentInfo(), transaction_party=TransactionParty(),
                          financial_attributes=FinancialAttributes(accounting_entity="Book A"),
                          evidence=[evidence], doc_id="doc-1")
    restored = LedgerRecord.model_validate_json(record.model_dump_json())
    assert restored.evidence[0].block_id == "p1:r3:c5"
    assert restored.evidence[0].field_name == "charge_details.amount"
    assert restored.doc_id == "doc-1"
    assert restored.record_kind == "charge_line"


def test_non_finite_amount_is_an_extraction_error():
    batch = parse_agent_response({"decisions": [raw_charge("NaN")]}, "Book A")
    assert not batch.decisions
    assert len(batch.extraction_errors) == 1


class FrozenChain:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def invoke(self, payload):
        self.calls.append(payload)
        return deepcopy(self.response)


def candidate_ledger():
    record = LedgerRecord(record_id="known-charge", charge_details=ChargeDetails(
        original_name="HANDLING CHARGE", amount="30", currency="USD"),
        document_info=DocumentInfo(document_number="TEST-INVOICE"),
        transaction_party=TransactionParty(),
        financial_attributes=FinancialAttributes(accounting_entity="Book A"))
    return Ledger(accounting_entity="Book A", records=[record])


def test_proposal_cannot_choose_unprovided_record_or_replace_extracted_facts():
    batch = parse_agent_response({"decisions": [raw_charge()]}, "Book A")
    agent = BillingAgent("Book A", use_mock=True)
    agent.proposal_chain = FrozenChain({"proposals": [{"item_index": 0, "operation": "UPDATE",
        "matched_record_id": "invented-id", "field_changes": {"charge_details.amount": "999"}}]})
    proposed = agent.propose_changes(batch, candidate_ledger())
    assert proposed.decisions[0].suggested_operation == "PENDING_REVIEW"
    assert proposed.decisions[0].matched_record_id is None
    assert proposed.decisions[0].charge_details.amount == Decimal("35.00")
    assert proposed.extraction_errors
    assert batch.decisions[0].suggested_operation == "CREATE"


def test_valid_proposal_adds_only_candidate_link_and_patch():
    batch = parse_agent_response({"decisions": [raw_charge()]}, "Book A")
    agent = BillingAgent("Book A", use_mock=True)
    agent.proposal_chain = FrozenChain({"proposals": [{"item_index": 0, "operation": "UPDATE",
        "matched_record_id": "known-charge", "field_changes": {"charge_details.amount": "35.00"},
        "reason": "Candidate has the same invoice and charge identity"}]})
    proposed = agent.propose_changes(batch, candidate_ledger())
    assert proposed.decisions[0].matched_record_id == "known-charge"
    assert proposed.decisions[0].field_changes == {"charge_details.amount": "35.00"}
    assert proposed.decisions[0].charge_details == batch.decisions[0].charge_details
    assert not proposed.decisions[0].revision_requested
    assert agent.proposal_chain.calls


def test_default_dictionary_is_explicit_in_model_context_and_instance_local():
    agent = BillingAgent("Book A", use_mock=True)
    assert agent.approved_charge_dictionary["handling charge"] == "HANDLING_CHARGE"
    agent.chain = FrozenChain({"decisions": [raw_charge()]})
    batch = agent.process_material("source text", Ledger(accounting_entity="Book A"))
    assert "HANDLING_CHARGE" in agent.chain.calls[0]["approved_charge_dictionary"]
    assert batch.decisions[0].charge_details.standardized_name == "HANDLING_CHARGE"
    agent.approved_charge_dictionary["new local fee"] = "LOCAL_FEE"
    assert "new local fee" not in CHARGE_NAME_MAPPING


def test_trusted_dictionary_injection_controls_mapping_not_model_returned_dictionary():
    row = raw_charge()
    row["charge_details"].update(original_name="Custom cost", standardized_name="CUSTOM_COST")
    response = {"decisions": [row], "approved_charge_dictionary": {"custom cost": "INVENTED"}}
    agent = BillingAgent("Book A", use_mock=True, approved_charge_dictionary={"CUSTOM COST": "CUSTOM_COST"})
    agent.chain = FrozenChain(response)
    batch = agent.process_material("source text", Ledger(accounting_entity="Book A"))
    assert batch.decisions[0].charge_details.standardized_name == "CUSTOM_COST"
    assert agent.approved_charge_dictionary == {"custom cost": "CUSTOM_COST"}
    assert not batch.extraction_errors


def test_unknown_model_mapping_is_not_accepted_as_approved():
    row = raw_charge()
    row["charge_details"].update(original_name="Unknown custom fee", standardized_name="MODEL_INVENTED")
    batch = parse_agent_response({"decisions": [row]}, "Book A")
    assert batch.decisions[0].charge_details.standardized_name is None
    assert batch.extraction_errors[0]["section"] == "charge_mapping"
    assert "unknown custom fee" not in CHARGE_NAME_MAPPING


def test_empty_dictionary_means_no_approved_mappings():
    agent = BillingAgent("Book A", use_mock=True, approved_charge_dictionary={})
    agent.chain = FrozenChain({"decisions": [raw_charge()]})
    batch = agent.process_material("source text", Ledger(accounting_entity="Book A"))
    assert agent.approved_charge_dictionary == {}
    assert batch.decisions[0].charge_details.standardized_name is None


def test_distinct_known_fees_map_without_ambiguous_hc_alias():
    expected = {
        "4 ADD'L DETENTION FREE TIME CHARGE": "DETENTION_FREE_TIME_CHARGE",
        "WHARFAGE": "WHARFAGE",
        "WHARFAGE ADMINISTRATION FEE": "WHARFAGE_ADMINISTRATION_FEE",
    }
    rows = []
    for name in expected:
        row = raw_charge()
        row["charge_details"]["original_name"] = name
        rows.append(row)
    hc = raw_charge()
    hc["charge_details"]["original_name"] = "H/C"
    batch = parse_agent_response({"decisions": [*rows, hc]}, "Book A")
    assert {d.charge_details.original_name: d.charge_details.standardized_name
            for d in batch.decisions[:-1]} == expected
    assert batch.decisions[-1].charge_details.standardized_name is None
    assert "h/c" not in CHARGE_NAME_MAPPING


def test_non_string_name_is_reported_without_losing_other_valid_rows():
    row = raw_charge()
    row["charge_details"]["original_name"] = 123
    batch = parse_agent_response({"decisions": [row, raw_charge()]}, "Book A")
    assert len(batch.decisions) == 1
    assert len(batch.extraction_errors) == 1
    assert batch.extraction_errors[0]["raw"] == row


def test_object_document_summary_is_normalized_without_losing_valid_fees():
    summary = {"document_total": None, "issuer": "湃乐多", "payer": None}
    response = {"decisions": [raw_charge()], "document_summary": summary}
    original = deepcopy(response)
    batch = parse_agent_response(response, "Book A")
    assert len(batch.decisions) == 1
    assert isinstance(batch.document_summary, str)
    assert json.loads(batch.document_summary) == summary
    assert batch.processing_metadata["raw_document_summary"] == summary
    assert batch.processing_metadata["normalization_warnings"][0]["field"] == "document_summary"
    assert batch.extraction_errors == []
    assert response == original


def test_list_document_summary_retains_all_structured_items():
    summary = [{"document_number": "INV-1"}, {"document_number": "INV-2"}]
    batch = parse_agent_response({"decisions": [], "document_summary": summary}, "Book A")
    assert json.loads(batch.document_summary) == summary
    assert batch.processing_metadata["raw_document_summary"] == summary


def test_text_and_null_document_summaries_preserve_existing_contract():
    for summary in ("两条费用，尚待核对", "", None):
        batch = parse_agent_response({"decisions": [], "document_summary": summary}, "Book A")
        assert batch.document_summary == summary
        assert "normalization_warnings" not in batch.processing_metadata


def test_real_agent_response_boundary_accepts_object_summary():
    agent = BillingAgent("Book A", use_mock=True)
    agent.chain = FrozenChain({"decisions": [raw_charge()], "document_summary": {"issuer": None}})
    batch = agent.process_material("frozen source text", Ledger(accounting_entity="Book A"))
    assert len(batch.decisions) == 1
    assert json.loads(batch.document_summary) == {"issuer": None}
