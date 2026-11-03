from decimal import Decimal

from src.billing_agent.agent import BillingAgent, parse_agent_response
from src.billing_agent.models import AgentDecisionBatch
from .test_extraction import FrozenChain, raw_charge
from .test_safe_billing import make_decision, source
from .test_safe_workflow import engine


def test_workflow_defaults_new_direction_and_accepts_raw_unmapped_fee(monkeypatch):
    monkeypatch.setenv("DEFAULT_POSTING_TYPE", "AR")
    monkeypatch.setenv("ALLOW_UNMAPPED_CHARGES", "true")
    item = make_decision()
    item.financial_attributes.posting_type = None
    item.charge_details.standardized_name = None
    flow = engine([item])
    preview = flow.prepare_batch(AgentDecisionBatch(decisions=[item]), source())
    assert preview["summary"]["operations"]["CREATE"] == 1
    row = preview["processing_results"][0]
    assert row["financial_attributes"]["posting_type"] == "AR"
    assert row["financial_attributes"]["posting_type_origin"] == "default"
    assert row["warnings"]
    result = flow.commit_preview(preview["preview_id"])
    assert result["committed"]
    flow.close()


def test_warning_and_resolved_issue_do_not_block_whole_batch():
    item = make_decision()
    flow = engine([item])
    preview = flow.prepare_batch(AgentDecisionBatch(decisions=[item]), source(), errors=[
        {"code": "DECORATIVE_ATTACHMENT", "message": "已确认是无关签名", "severity": "warning"},
        {"code": "POSTING_TYPE_MISSING", "message": "方向缺失", "status": "resolved", "severity": "error"},
    ])
    assert preview["summary"]["operations"]["CREATE"] == 1
    result = flow.commit_preview(preview["preview_id"])
    assert result["committed"]
    flow.close()


def test_unknown_model_mapping_is_warning_only_under_explicit_lenient_policy():
    raw = raw_charge()
    raw["charge_details"].update(original_name="New fee", standardized_name="INVENTED")
    batch = parse_agent_response({"decisions": [raw]}, "A", allow_unmapped_charges=True)
    assert batch.decisions[0].charge_details.standardized_name is None
    assert all(e.get("severity") == "warning" for e in batch.extraction_errors)
    assert batch.processing_metadata["mapping_suggestions"][0]["suggested_code"] == "INVENTED"


def test_identity_repair_cannot_replace_amount_and_is_called_only_once():
    agent = BillingAgent("A", use_mock=True)
    item = make_decision()
    item.transaction_party.issuer = None
    agent.identity_chain = FrozenChain({"repairs": [{"item_index": 0,
        "document_info": {"document_type": "INVOICE"},
        "transaction_party": {"issuer": "Issuer"},
        "evidence": [{"source_file": "bill.txt", "source_type": "text", "source_id": "src-1",
                      "block_id": "b1", "original_text": "Issuer", "field_name": "transaction_party.issuer"}]}]})
    batch = agent.repair_missing_identity(AgentDecisionBatch(decisions=[item]), source())
    assert batch.decisions[0].transaction_party.issuer == "Issuer"
    assert batch.decisions[0].charge_details.amount == Decimal("40")
    assert batch.processing_metadata["identity_repair_attempted"] is True


def test_parser_retains_structured_review_issues_for_policy_resolution():
    raw = raw_charge()
    raw["review_issues"] = [{"code": "POSTING_TYPE_MISSING", "message": "方向缺失"}]
    batch = parse_agent_response({"decisions": [raw]}, "A")
    assert batch.decisions[0].review_issues[0]["code"] == "POSTING_TYPE_MISSING"


def test_strict_mapping_mode_does_not_release_model_warning():
    item = make_decision()
    flow = engine([item])
    flow.allow_unmapped_charges = False
    preview = flow.prepare_batch(AgentDecisionBatch(decisions=[item], extraction_errors=[{
        "code": "CHARGE_MAPPING_UNKNOWN", "severity": "warning", "message": "费用代码待确认"}]), source())
    assert preview["summary"]["operations"]["PENDING_REVIEW"] == 1
    flow.close()


def test_identity_repair_does_not_borrow_issuer_from_unrelated_file():
    agent = BillingAgent("A", use_mock=True)
    item = make_decision()
    item.transaction_party.issuer = None
    material = source()
    material[0]["blocks"][0]["text"] = "INV-1 HANDLING USD 40"
    material[0]["content"] = "INV-1 HANDLING USD 40"
    material.append({"source_id": "unrelated", "source_file": "other.txt", "content": "INV-2 OtherIssuer",
        "blocks": [{"source_id": "unrelated", "block_id": "other", "text": "INV-2 OtherIssuer"}]})
    agent.identity_chain = FrozenChain({"repairs": [{"item_index": 0,
        "transaction_party": {"issuer": "OtherIssuer"}, "evidence": [{"source_file": "other.txt",
            "source_type": "text", "source_id": "unrelated", "block_id": "other",
            "original_text": "OtherIssuer", "field_name": "transaction_party.issuer"}]}]})
    repaired = agent.repair_missing_identity(AgentDecisionBatch(decisions=[item]), material)
    assert repaired.decisions[0].transaction_party.issuer is None
