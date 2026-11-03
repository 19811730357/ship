"""Posting policies resolve routine gaps without hiding genuine conflicts."""
from decimal import Decimal

import pytest

from src.billing_agent.database import DatabaseManager
from src.billing_agent.models import (
    AgentDecision, ChargeDetails, DocumentInfo, Evidence, FinancialAttributes,
    LedgerRecord, TransactionParty,
)
from src.billing_agent.smart_crud import SmartCRUDExecutor


def test_unproven_model_direction_does_not_override_unique_old_ap(db):
    store_old(db, "AP")
    plan = SmartCRUDExecutor(db, "A", default_posting_type="AR").plan(
        decision("AR", "model_inferred"), sources())
    assert plan["operation"] == "NO_CHANGE"
    assert plan["decision"]["financial_attributes"]["posting_type"] == "AP"
    assert plan["decision"]["financial_attributes"]["posting_type_origin"] == "inherited"


@pytest.fixture
def db():
    manager = DatabaseManager("sqlite", {"database": ":memory:"})
    yield manager
    manager.close()


def decision(direction=None, origin=None, mapped=True):
    return AgentDecision(
        suggested_operation="CREATE", operation_reasoning="extracted", confidence="HIGH",
        charge_details=ChargeDetails(
            original_name="HANDLING" if mapped else "Vendor OCA17",
            standardized_name="HANDLING_CHARGE" if mapped else None,
            amount=Decimal("50"), currency="USD", line_reference="L1"),
        document_info=DocumentInfo(document_number="INV-1", document_type="INVOICE"),
        transaction_party=TransactionParty(issuer="Issuer"),
        financial_attributes=FinancialAttributes(
            accounting_entity="A", posting_type=direction, posting_type_origin=origin),
        evidence=[Evidence(source_file="bill.txt", source_type="text", source_id="src-1",
                           block_id="b1", original_text="HANDLING Vendor OCA17 USD 50")],
    )


def sources():
    text = "INV-1 Issuer HANDLING Vendor OCA17 USD 50"
    return [{"source_id": "src-1", "source_file": "bill.txt", "content": text,
             "blocks": [{"source_id": "src-1", "block_id": "b1", "text": text}]}]


def store_old(db, direction="AP"):
    d = decision(direction)
    db.save_ledger_record(LedgerRecord(
        record_id="old", version=7, charge_details=d.charge_details,
        document_info=d.document_info, transaction_party=d.transaction_party,
        financial_attributes=d.financial_attributes))


def test_new_charge_uses_configured_ar_and_records_policy(db):
    d = decision()
    plan = SmartCRUDExecutor(db, "A", default_posting_type="AR").plan(d, sources())
    assert plan["operation"] == "CREATE"
    financial = plan["after"]["financial_attributes"]
    assert financial["posting_type"] == "AR"
    assert financial["posting_type_origin"] == "default"
    assert financial["policy_version"]
    assert "AR" in financial["posting_type_reasoning"]
    assert any(issue["code"] == "POSTING_TYPE_DEFAULTED" for issue in plan["warnings"])
    assert d.financial_attributes.posting_type is None


def test_missing_direction_stays_pending_without_configured_rule(db):
    plan = SmartCRUDExecutor(db, "A").plan(decision(), sources())
    assert plan["operation"] == "PENDING_REVIEW"
    assert "AR/AP交易方向待确认" in plan["validation_issues"]


@pytest.mark.parametrize("incoming,origin", [(None, None), ("AR", "default")])
def test_unique_old_ap_is_inherited_before_new_charge_default(db, incoming, origin):
    store_old(db)
    plan = SmartCRUDExecutor(db, "A", default_posting_type="AR").plan(
        decision(incoming, origin), sources())
    assert plan["operation"] == "NO_CHANGE"
    financial = plan["decision"]["financial_attributes"]
    assert financial["posting_type"] == "AP"
    assert financial["posting_type_origin"] == "inherited"
    assert db.get_record("old", "A").version == 7


def test_explicit_new_ap_wins_over_configured_ar(db):
    plan = SmartCRUDExecutor(db, "A", default_posting_type="AR").plan(
        decision("AP", "explicit"), sources())
    assert plan["operation"] == "CREATE"
    assert plan["after"]["financial_attributes"]["posting_type"] == "AP"
    assert not any(i["code"] == "POSTING_TYPE_DEFAULTED" for i in plan["warnings"])


def test_explicit_direction_conflict_with_old_ap_remains_pending(db):
    store_old(db)
    plan = SmartCRUDExecutor(db, "A", default_posting_type="AR").plan(
        decision("AR", "explicit"), sources())
    assert plan["operation"] == "PENDING_REVIEW"
    assert any("财务属性变化" in issue for issue in plan["validation_issues"])


def test_unmapped_raw_charge_can_be_created_with_a_warning(db):
    plan = SmartCRUDExecutor(db, "A", default_posting_type="AR", allow_unmapped_charges=True).plan(
        decision(mapped=False), sources())
    assert plan["operation"] == "CREATE"
    assert plan["after"]["charge_details"]["original_name"] == "Vendor OCA17"
    assert plan["after"]["charge_details"]["standardized_name"] is None
    assert any(i["code"] == "CHARGE_MAPPING_UNKNOWN" for i in plan["warnings"])


def test_unmapped_charge_is_still_pending_in_strict_mode(db):
    plan = SmartCRUDExecutor(db, "A", default_posting_type="AR").plan(
        decision(mapped=False), sources())
    assert plan["operation"] == "PENDING_REVIEW"
    assert "标准费用映射待确认" in plan["validation_issues"]


def test_allow_unmapped_does_not_approve_invented_standard_code(db):
    d = decision(mapped=False)
    d.charge_details.standardized_name = "INVENTED"
    plan = SmartCRUDExecutor(db, "A", default_posting_type="AR", allow_unmapped_charges=True).plan(
        d, sources())
    assert plan["operation"] == "PENDING_REVIEW"
    assert any("字典" in issue for issue in plan["validation_issues"])


def test_model_pending_for_resolved_direction_is_recomputed(db):
    d = decision()
    d.suggested_operation = "PENDING_REVIEW"
    d.operation_reasoning = "AR/AP交易方向待确认"
    plan = SmartCRUDExecutor(db, "A", default_posting_type="AR").plan(d, sources())
    assert plan["operation"] == "CREATE"
    assert any(i["code"] == "POSTING_TYPE_MISSING" for i in plan["resolved_issues"])


def test_resolved_direction_does_not_hide_structured_amount_issue(db):
    d = decision()
    d.suggested_operation = "PENDING_REVIEW"
    d.operation_reasoning = "AR/AP交易方向待确认"
    d.review_issues = [
        {"code": "POSTING_TYPE_MISSING", "message": "AR/AP交易方向待确认"},
        {"code": "TOTAL_MISMATCH", "message": "明细300，总额245"},
    ]
    plan = SmartCRUDExecutor(db, "A", default_posting_type="AR").plan(d, sources())
    assert plan["operation"] == "PENDING_REVIEW"
    assert any("明细300" in issue for issue in plan["validation_issues"])


def test_vague_model_pending_is_not_silently_approved(db):
    d = decision()
    d.suggested_operation = "PENDING_REVIEW"
    d.operation_reasoning = "需要进一步检查所有材料"
    plan = SmartCRUDExecutor(db, "A", default_posting_type="AR").plan(d, sources())
    assert plan["operation"] == "PENDING_REVIEW"
    assert any("需要进一步检查" in issue for issue in plan["validation_issues"])


def test_resolved_mapping_warning_can_release_only_mapping_pending(db):
    d = decision(mapped=False)
    d.suggested_operation = "PENDING_REVIEW"
    d.operation_reasoning = "标准费用映射待确认"
    plan = SmartCRUDExecutor(db, "A", default_posting_type="AR", allow_unmapped_charges=True).plan(d, sources())
    assert plan["operation"] == "CREATE"
    assert any(i["code"] == "CHARGE_MAPPING_UNKNOWN" for i in plan["resolved_issues"])


def test_human_direction_correction_retains_human_origin_in_saved_record(db):
    store_old(db)
    plan = SmartCRUDExecutor(db, "A", default_posting_type="AR").plan(
        decision(), sources(), review={"record_id": "old", "posting_type": "AR", "note": "已核对方向"})
    assert plan["operation"] == "UPDATE"
    assert plan["after"]["financial_attributes"]["posting_type_origin"] == "human"


def test_invalid_posting_policy_is_rejected(db):
    with pytest.raises(ValueError, match="AR|AP"):
        SmartCRUDExecutor(db, "A", default_posting_type="INVALID")


def test_identity_pending_can_be_recomputed_after_supported_fields_are_filled(db):
    d = decision("AR", "explicit")
    d.suggested_operation = "PENDING_REVIEW"
    d.operation_reasoning = "新增费用缺少完整单据身份"
    plan = SmartCRUDExecutor(db, "A").plan(d, sources())
    assert plan["operation"] == "CREATE"
    assert any(i["code"] == "DOCUMENT_IDENTITY_MISSING" and i["status"] == "resolved_by_reextraction"
               for i in plan["resolved_issues"])


def test_invented_code_is_not_reported_as_a_resolved_mapping(db):
    d = decision("AR", "explicit", mapped=False)
    d.charge_details.standardized_name = "INVENTED"
    d.suggested_operation = "PENDING_REVIEW"
    d.operation_reasoning = "标准费用映射待确认"
    plan = SmartCRUDExecutor(db, "A", allow_unmapped_charges=True).plan(d, sources())
    assert plan["operation"] == "PENDING_REVIEW"
    assert not any(i["code"] == "CHARGE_MAPPING_UNKNOWN" for i in plan["resolved_issues"])


def test_structured_amount_issue_blocks_even_if_model_suggested_create(db):
    d = decision("AR", "explicit")
    d.review_issues = [{"code": "TOTAL_MISMATCH", "message": "原文金额存在冲突"}]
    plan = SmartCRUDExecutor(db, "A").plan(d, sources())
    assert plan["operation"] == "PENDING_REVIEW"
    assert any("原文金额存在冲突" in issue for issue in plan["validation_issues"])
