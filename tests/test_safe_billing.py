from decimal import Decimal

import pytest

from src.billing_agent.database import DatabaseManager
from src.billing_agent.models import (
    AgentDecision, ChargeDetails, DocumentInfo, Evidence,
    FinancialAttributes, LedgerRecord, TransactionParty,
)
from src.billing_agent.smart_crud import SmartCRUDExecutor


def make_decision(amount="40", entity="A", number="INV-1", line="L1"):
    return AgentDecision(
        suggested_operation="CREATE", operation_reasoning="extracted", confidence="HIGH",
        charge_details=ChargeDetails(original_name="HANDLING", standardized_name="HANDLING_CHARGE",
                                     amount=Decimal(amount), currency="USD", line_reference=line),
        document_info=DocumentInfo(document_number=number, document_type="INVOICE"),
        transaction_party=TransactionParty(issuer="Issuer"),
        financial_attributes=FinancialAttributes(accounting_entity=entity, posting_type="AP",
                                                posting_type_reasoning="Company A is payer"),
        evidence=[Evidence(source_file="bill.txt", source_type="text", source_id="src-1",
                           block_id="b1", original_text=f"HANDLING USD {amount}")],
    )


def make_record(amount="50", entity="A", record_id="old", line="L1"):
    d = make_decision(amount, entity, line=line)
    d.document_info.booking_number = "KEEP"
    return LedgerRecord(record_id=record_id, charge_details=d.charge_details,
                        document_info=d.document_info, transaction_party=d.transaction_party,
                        financial_attributes=d.financial_attributes, version=7)


def source(amount="40", extra=""):
    text = f"INV-1 Issuer A pays Issuer HANDLING USD {amount} {extra}".strip()
    return [{"source_id": "src-1", "source_file": "bill.txt", "content": text,
             "blocks": [{"source_id": "src-1", "block_id": "b1", "text": text}]}]


@pytest.fixture
def db():
    manager = DatabaseManager("sqlite", {"database": ":memory:"})
    yield manager
    manager.close()


def test_lookup_requires_entity_and_never_returns_other_entity(db):
    db.save_ledger_record(make_record(entity="A"))
    assert db.query_records_by_document("INV-1", "B") == []


def test_planning_does_not_write(db):
    executor = SmartCRUDExecutor(db, "A")
    plan = executor.plan(make_decision(), source())
    assert plan["operation"] == "CREATE"
    assert db.load_ledger("A").records == []


def test_different_amount_without_revision_is_review(db):
    db.save_ledger_record(make_record())
    plan = SmartCRUDExecutor(db, "A").plan(make_decision(), source(), allow_updates=True)
    assert plan["operation"] == "PENDING_REVIEW"
    assert db.load_ledger("A").records[0].charge_details.amount == Decimal("50")


def test_ambiguous_same_name_does_not_create_third_record(db):
    db.save_ledger_record(make_record("65", record_id="first", line=None))
    db.save_ledger_record(make_record("35", record_id="second", line=None))
    plan = SmartCRUDExecutor(db, "A").plan(make_decision(line=None), source(), allow_updates=True)
    assert plan["operation"] == "PENDING_REVIEW"
    assert len(plan["candidates"]) == 2
    assert len(db.load_ledger("A").records) == 2


def test_explicit_revision_preserves_unprovided_fields_and_version(db):
    db.save_ledger_record(make_record())
    d = make_decision()
    d.revision_requested = True
    d.field_changes = {"charge_details.amount": "40"}
    d.revision_evidence = [Evidence(source_file="bill.txt", source_type="text", source_id="src-1",
                                   block_id="b1", original_text="Please revise INV-1 line L1 to USD 40")]
    sources = source(extra="Please revise INV-1 line L1 to USD 40")
    plan = SmartCRUDExecutor(db, "A").plan(d, sources, allow_updates=True)
    assert plan["operation"] == "UPDATE"
    db.commit_plans([plan], [], "session-1", "A")
    record = db.load_ledger("A").records[0]
    assert record.charge_details.amount == Decimal("40")
    assert record.document_info.booking_number == "KEEP"
    assert record.version == 8
    assert len(record.audit_history) == 1
    assert record.audit_history[0].old_values["charge_details"]["amount"] == "50"


def test_stale_preview_does_not_overwrite_current_record(db):
    original = make_record()
    db.save_ledger_record(original)
    executor = SmartCRUDExecutor(db, "A")
    plan = executor.plan(make_decision(), source(), review={"record_id": "old", "note": "checked original"})
    changed = original.model_copy(deep=True)
    changed.version += 1
    changed.charge_details.amount = Decimal("60")
    db.save_ledger_record(changed)
    with pytest.raises(ValueError, match="版本|version"):
        db.commit_plans([plan], [], "session-stale", "A")
    assert db.load_ledger("A").records[0].charge_details.amount == Decimal("60")


def test_audit_failure_rolls_back_charge_and_source(db, monkeypatch):
    plan = SmartCRUDExecutor(db, "A").plan(make_decision(), source())
    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")
    monkeypatch.setattr(db, "_write_change", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        db.commit_plans([plan], [{"document_hash": "abc", "file_name": "bill.txt", "status": "committed"}],
                        "session-fail", "A")
    assert db.load_ledger("A").records == []
    assert db.check_document_processed(b"bill", "A") is None


def test_source_dedup_is_scoped_and_pending_can_retry(db):
    db.save_document_processing(b"bill", "bill.txt", "pending_review", {}, "A")
    assert db.check_document_processed(b"bill", "A") is None
    db.save_document_processing(b"bill", "bill.txt", "committed", {}, "A")
    assert db.check_document_processed(b"bill", "A") is not None
    assert db.check_document_processed(b"bill", "B") is None


def test_missing_identity_is_not_automatic_create(db):
    d = make_decision()
    d.document_info.document_number = None
    plan = SmartCRUDExecutor(db, "A").plan(d, source())
    assert plan["operation"] == "PENDING_REVIEW"


def test_fabricated_evidence_is_not_accepted(db):
    d = make_decision()
    d.evidence[0].original_text = "NOT IN SOURCE 40 USD"
    plan = SmartCRUDExecutor(db, "A").plan(d, source())
    assert plan["operation"] == "PENDING_REVIEW"


def test_explicit_different_line_reference_is_not_same_charge(db):
    db.save_ledger_record(make_record("40", line="L1"))
    plan = SmartCRUDExecutor(db, "A").plan(make_decision(line="L2"), source())
    assert plan["operation"] == "PENDING_REVIEW"


def test_changed_posting_direction_is_not_silent_no_change(db):
    db.save_ledger_record(make_record("40"))
    d = make_decision()
    d.financial_attributes.posting_type = "AR"
    plan = SmartCRUDExecutor(db, "A").plan(d, source())
    assert plan["operation"] == "PENDING_REVIEW"


def test_human_can_correct_only_posting_direction(db):
    db.save_ledger_record(make_record("40"))
    plan = SmartCRUDExecutor(db, "A").plan(make_decision(), source(),
        review={"record_id": "old", "posting_type": "AR", "note": "核对付款关系"})
    assert plan["operation"] == "UPDATE"
    assert plan["after"]["financial_attributes"]["posting_type"] == "AR"


def test_booking_number_does_not_count_as_amount_evidence(db):
    d = make_decision()
    d.evidence[0].original_text = "Booking 40"
    sources = source()
    sources[0]["content"] = "Booking 40"
    sources[0]["blocks"][0]["text"] = "Booking 40"
    plan = SmartCRUDExecutor(db, "A").plan(d, sources)
    assert plan["operation"] == "PENDING_REVIEW"


def test_invalid_human_posting_direction_is_reviewed_not_persisted(db):
    plan = SmartCRUDExecutor(db, "A").plan(make_decision(), source(),
        review={"approve_create": True, "posting_type": "INVALID", "note": "manual correction"})
    assert plan["operation"] == "PENDING_REVIEW"


def test_existing_direction_and_standard_name_survive_missing_new_values(db):
    db.save_ledger_record(make_record("40"))
    d = make_decision()
    d.financial_attributes.posting_type = None
    d.charge_details.standardized_name = None
    plan = SmartCRUDExecutor(db, "A").plan(d, source())
    assert plan["operation"] == "NO_CHANGE"


def test_model_review_warning_is_not_silently_turned_into_create(db):
    d = make_decision()
    d.suggested_operation = "PENDING_REVIEW"
    d.operation_reasoning = "fee service scope unclear"
    plan = SmartCRUDExecutor(db, "A").plan(d, source())
    assert plan["operation"] == "PENDING_REVIEW"


def test_invented_standard_code_requires_manual_approval(db):
    d = make_decision()
    d.charge_details.standardized_name = "INVENTED"
    plan = SmartCRUDExecutor(db, "A").plan(d, source())
    assert plan["operation"] == "PENDING_REVIEW"


def test_legacy_conflict_resolver_never_uses_high_confidence_to_bypass_review():
    from src.billing_agent.ledger import resolve_operation
    from src.billing_agent.models import Ledger, ValidationResult
    d = make_decision()
    d.suggested_operation = "UPDATE"
    d.matched_record_id = "old"
    validation = ValidationResult(is_valid=True, program_operation="PENDING_REVIEW")
    result = resolve_operation(d, validation, Ledger(accounting_entity="A", records=[make_record()]))
    assert result.operation == "PENDING_REVIEW"


def test_invented_document_number_is_not_accepted_from_amount_quote(db):
    d = make_decision(number="INVENTED-123")
    plan = SmartCRUDExecutor(db, "A").plan(d, source())
    assert plan["operation"] == "PENDING_REVIEW"


def test_dollar_symbol_does_not_prove_usd_even_if_model_guesses_usd(db):
    d = make_decision()
    d.evidence[0].original_text = "HANDLING $40"
    sources = source()
    sources[0]["content"] = sources[0]["content"].replace("USD 40", "$40")
    sources[0]["blocks"][0]["text"] = sources[0]["content"]
    plan = SmartCRUDExecutor(db, "A").plan(d, sources)
    assert plan["operation"] == "PENDING_REVIEW"


def test_amount_outside_shared_database_precision_is_reviewed(db):
    d = make_decision("1.000000001")
    plan = SmartCRUDExecutor(db, "A").plan(d, source("1.000000001"))
    assert plan["operation"] == "PENDING_REVIEW"


def test_audit_business_snapshots_do_not_recursively_embed_old_audits(db):
    db.save_ledger_record(make_record())
    planner = SmartCRUDExecutor(db, "A")
    plan = planner.plan(make_decision(), source(), review={"record_id": "old", "note": "checked source"})
    audit = plan["after"]["audit_history"][-1]
    assert "audit_history" not in audit["old_values"]
    assert "audit_history" not in audit["new_values"]
