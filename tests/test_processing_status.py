"""Processing failures and skipped source observations remain explicit in results."""

from copy import deepcopy
from decimal import Decimal
import json

import pytest

from src.billing_agent.models import AgentDecisionBatch
from .test_safe_billing import make_decision, source
from .test_safe_workflow import engine


@pytest.mark.parametrize("error", [
    {"section": "model", "error": "model request failed"},
    {"section": "model", "error": "invalid JSON"},
    {"error": "unclassified extraction failure"},
])
def test_empty_extraction_with_unresolved_error_is_processing_failed(error):
    flow = engine([])
    try:
        result = flow.prepare_batch(AgentDecisionBatch(extraction_errors=[error]), source())
        assert result["processing_results"] == []
        assert result["run_report"]["processing_status"] == "PROCESSING_FAILED"
    finally:
        flow.close()


def test_model_transport_failure_remains_processing_failed_even_with_retained_rows():
    flow = engine([make_decision()])
    try:
        result = flow.prepare_batch(AgentDecisionBatch(decisions=[make_decision()], extraction_errors=[
            {"section": "model", "error": "second model response invalid JSON"}]), source())
        assert result["processing_results"][0]["operation"] == "PENDING_REVIEW"
        assert result["run_report"]["processing_status"] == "PROCESSING_FAILED"
    finally:
        flow.close()


def test_business_total_conflict_is_pending_review_not_processing_failed():
    item = make_decision()
    item.document_info.document_total = Decimal("99")
    item.document_info.total_currency = "USD"
    flow = engine([item])
    try:
        result = flow.prepare_batch(AgentDecisionBatch(decisions=[item]), source())
        assert result["summary"]["operations"]["PENDING_REVIEW"] == 1
        assert result["run_report"]["processing_status"] == "PENDING_REVIEW"
    finally:
        flow.close()


def test_resolved_and_warning_source_issues_leave_preview_ready():
    flow = engine([make_decision()])
    try:
        result = flow.prepare_batch(AgentDecisionBatch(decisions=[make_decision()]), source(), errors=[
            {"origin": "parser", "message": "confirmed logo skipped", "severity": "warning"},
            {"origin": "parser", "message": "source checked", "status": "resolved"},
        ])
        assert result["run_report"]["processing_status"] == "PREVIEW_READY"
        committed = flow.commit_preview(result["preview_id"])
        assert committed["run_report"]["processing_status"] == "COMMITTED"
    finally:
        flow.close()


@pytest.mark.parametrize("nested", [False, True])
def test_skipped_observation_paths_are_saved_without_becoming_model_input(tmp_path, nested):
    path = tmp_path / "material.eml"
    path.write_bytes(b"source observation test")
    skipped_path = str(tmp_path / "skipped-observation.json")
    skipped = {"source_id": "decorative-source", "source_file": "logo.png", "blocks": [], "content": "",
               "metadata": {"skipped": True, "observation_path": skipped_path},
               "attachments": [], "errors": [{"severity": "warning", "message": "confirmed logo"}]}
    if nested:
        parent_path = str(tmp_path / "mail-observation.json")
        parsed = {**deepcopy(source()[0]), "source_type": "email",
                  "metadata": {"observation_path": parent_path},
                  "attachments": [{"parsed": skipped}], "errors": skipped["errors"]}
        flow = engine([make_decision()])
        expected = [parent_path, skipped_path]
    else:
        parsed = skipped
        flow = engine([])
        expected = [skipped_path]

    class FrozenParser:
        def parse_file(self, _):
            return deepcopy(parsed)

    flow.parser = FrozenParser()
    try:
        result = flow.process_real_files([path])
        assert all(s["source_id"] != "decorative-source" for s in result["source_documents"])
        flow.commit_preview(result["preview_id"])
        row = flow.db._execute("SELECT results FROM billing_sources WHERE accounting_entity=?", ("A",)).fetchone()
        saved = json.loads(row["results"])
        assert saved["observation_paths"] == expected
    finally:
        flow.close()
