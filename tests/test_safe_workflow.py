from decimal import Decimal

import pytest

from src.billing_agent.database import DatabaseManager
from src.billing_agent.ledger import load_ledger_from_dict
from src.billing_agent.models import AgentDecisionBatch
from src.billing_agent.workflow import BillingWorkflow
from src.billing_agent.workflow_db import DatabaseWorkflow
from .test_safe_billing import make_decision, make_record, source


class FrozenAgent:
    def __init__(self, decisions, errors=None):
        self.batch = AgentDecisionBatch(decisions=decisions, extraction_errors=errors or [])
        self.calls = 0

    def process_material(self, text, ledger):
        self.calls += 1
        assert "b1" in text
        return self.batch.model_copy(deep=True)


class FrozenParser:
    def parse_file(self, path):
        return {**source()[0], "source_type": "text", "attachments": [], "errors": [], "metadata": {}}


@pytest.fixture
def materials(tmp_path):
    path = tmp_path / "bill.txt"
    path.write_text("HANDLING USD 40", encoding="utf-8")
    return [path]


def engine(decisions, db=None, errors=None):
    return DatabaseWorkflow("A", db_manager=db or DatabaseManager("sqlite", {"database": ":memory:"}),
                            agent=FrozenAgent(decisions, errors), parser=FrozenParser())


def test_default_preview_does_not_write_and_explicit_commit_does(materials):
    flow = engine([make_decision()])
    preview = flow.process_real_files(materials)
    assert preview["preview_only"] and not preview["committed"]
    assert flow.db.load_ledger("A").records == []
    result = flow.commit_preview(preview["preview_id"])
    assert result["committed"]
    assert result["ledger_snapshot"]["records"][0]["charge_details"]["amount"] == "40"


def test_complete_snapshot_can_roundtrip(materials):
    flow = engine([make_decision()])
    flow.db.save_ledger_record(make_record(record_id="unrelated", entity="A"))
    flow.db.get_record("unrelated", "A")
    # Different document guarantees the old row remains part of the complete snapshot.
    old = flow.db.get_record("unrelated", "A")
    old.document_info.document_number = "OTHER"
    flow.db.save_ledger_record(old)
    result = flow.process_real_files(materials, preview_only=False)
    ledger = load_ledger_from_dict(result["ledger_snapshot"], "A")
    assert len(ledger.records) == 2
    assert ledger.get_record("unrelated").document_info.booking_number == "KEEP"


def test_extraction_errors_block_commit_and_do_not_poison_dedup(materials):
    flow = engine([make_decision()], errors=[{"error": "second line unreadable"}])
    result = flow.process_real_files(materials, preview_only=False)
    assert not flow.db.load_ledger("A").records
    assert result["summary"]["operations"]["PENDING_REVIEW"] == 1
    assert flow.db.check_document_processed(materials[0].read_bytes(), "A") is None


def test_human_selection_updates_only_selected_same_name_charge(materials):
    db = DatabaseManager("sqlite", {"database": ":memory:"})
    db.save_ledger_record(make_record("65", record_id="first", line=None))
    db.save_ledger_record(make_record("35", record_id="second", line=None))
    flow = engine([make_decision(line=None)], db)
    preview = flow.process_real_files(materials)
    item = preview["processing_results"][0]["item_id"]
    result = flow.commit_preview(preview["preview_id"], {item: {"record_id": "second", "note": "核对原单第二笔费用"}})
    assert result["committed"]
    assert db.get_record("first", "A").charge_details.amount == Decimal("65")
    assert db.get_record("second", "A").charge_details.amount == Decimal("40")


def test_commit_rechecks_version(materials):
    flow = engine([make_decision()])
    flow.db.save_ledger_record(make_record())
    preview = flow.process_real_files(materials)
    old = flow.db.get_record("old", "A")
    old.version += 1
    flow.db.save_ledger_record(old)
    item = preview["processing_results"][0]["item_id"]
    with pytest.raises(ValueError, match="版本|version"):
        flow.commit_preview(preview["preview_id"], {item: {"record_id": "old", "note": "review"}})


def test_second_commit_of_same_preview_is_idempotent(materials):
    flow = engine([make_decision()])
    preview = flow.process_real_files(materials)
    flow.commit_preview(preview["preview_id"])
    result = flow.commit_preview(preview["preview_id"])
    assert len(flow.db.load_ledger("A").records) == 1
    assert result["summary"]["operations"]["CREATE"] == 0


def test_non_database_workflow_accepts_same_options(materials):
    flow = BillingWorkflow("A", agent=FrozenAgent([make_decision()]), parser=FrozenParser())
    result = flow.process_real_files(materials, force_reprocess=False, preview_only=True)
    assert result["preview_id"]
    assert not result["committed"]


def test_total_conflict_cannot_be_bypassed_by_manual_approval(materials):
    d = make_decision()
    d.document_info.document_total = Decimal("100")
    d.document_info.total_currency = "USD"
    flow = engine([d])
    preview = flow.process_real_files(materials)
    item = preview["processing_results"][0]["item_id"]
    result = flow.commit_preview(preview["preview_id"], {item: {"approve_create": True, "note": "review"}})
    assert not flow.db.load_ledger("A").records
    assert result["summary"]["operations"]["PENDING_REVIEW"] == 1


def test_partial_preview_does_not_ignore_later_external_edit(materials):
    first, second = make_decision(), make_decision(number="INV-2")
    second.charge_details.standardized_name = None
    flow = engine([first, second])
    preview = flow.process_real_files(materials)
    result = flow.commit_preview(preview["preview_id"])
    record = flow.db.load_ledger("A").records[0]
    record.version += 1
    record.charge_details.amount = Decimal("70")
    flow.db.save_ledger_record(record)
    with pytest.raises(ValueError, match="版本|version"):
        flow.commit_preview(preview["preview_id"], {"1": {"approve_create": True,
            "standardized_name": "HANDLING_CHARGE", "note": "review"}})


def test_legacy_upload_is_not_automatically_treated_as_individual_charge(materials):
    old = make_record().model_dump(mode="json")
    old.pop("record_kind", None)
    flow = engine([make_decision()])
    preview = flow.process_real_files(materials, ledger_data=[old], allow_updates=True)
    assert preview["processing_results"][0]["candidates"][0]["record_kind"] == "legacy_summary"


def test_confirmed_unrelated_parser_issue_can_be_excluded_with_audit(materials):
    flow = engine([make_decision()])
    parsed_source = source()
    preview = flow.prepare_batch(AgentDecisionBatch(decisions=[make_decision()]), parsed_source,
        errors=[{"error": "signature logo OCR unavailable", "reviewable": True, "origin": "parser"}])
    assert preview["summary"]["operations"]["PENDING_REVIEW"] == 1
    result = flow.commit_preview(preview["preview_id"], {"__source_reviews__": [
        {"issue_index": 0, "exclude": True, "note": "已核对为邮件签名广告图，与费用无关"}]})
    assert result["committed"]
    assert result["run_report"]["reviewed_source_issues"][0]["note"]


def test_same_source_row_duplicated_by_model_cannot_commit_twice():
    first, duplicate = make_decision(), make_decision()
    flow = engine([first, duplicate])
    preview = flow.prepare_batch(AgentDecisionBatch(decisions=[first, duplicate]), source())
    result = flow.commit_preview(preview["preview_id"])
    assert flow.db.load_ledger("A").records == []
    assert result["summary"]["operations"]["PENDING_REVIEW"] == 2


def test_cross_source_conflict_is_rechecked_at_commit():
    first, second = make_decision(), make_decision()
    second.evidence[0].source_id = "src-2"
    second.evidence[0].block_id = "b2"
    sources = source()
    sources.append({"source_id": "src-2", "source_file": "copy.txt", "content": "HANDLING USD 40",
                    "blocks": [{"source_id": "src-2", "block_id": "b2", "text": "HANDLING USD 40"}]})
    flow = engine([first, second])
    preview = flow.prepare_batch(AgentDecisionBatch(decisions=[first, second]), sources)
    result = flow.commit_preview(preview["preview_id"])
    assert flow.db.load_ledger("A").records == []
    assert result["summary"]["operations"]["PENDING_REVIEW"] == 2


def test_model_cannot_label_extraction_error_as_excludable_parser_issue(materials):
    flow = engine([make_decision()], errors=[{"error": "unreadable fee", "origin": "parser", "reviewable": True}])
    preview = flow.process_real_files(materials)
    assert preview["run_report"]["file_errors"][0]["reviewable"] is False
    with pytest.raises(ValueError, match="来源问题"):
        flow.commit_preview(preview["preview_id"], {"__source_reviews__": [
            {"issue_index": 0, "exclude": True, "note": "should not bypass extraction completeness"}]})


def test_structured_summary_does_not_turn_valid_extraction_into_empty_failed_preview(materials):
    from src.billing_agent.agent import BillingAgent
    from .test_extraction import FrozenChain
    agent = BillingAgent("A", use_mock=True)
    agent.chain = FrozenChain({"decisions": [make_decision().model_dump(mode="json")],
                               "document_summary": {"document_total": None, "issuer": None, "payer": None}})
    flow = DatabaseWorkflow("A", db_config={"database": ":memory:"}, agent=agent, parser=FrozenParser())
    result = flow.process_real_files(materials)
    assert len(result["processing_results"]) == 1
    assert result["run_report"]["file_errors"] == []
    assert flow.db.load_ledger("A").records == []
