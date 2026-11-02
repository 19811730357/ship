"""Offline UI contracts: preview lifecycle, exact amounts and safe uploads."""

import ast
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[1]


def app_helpers():
    """Load pure helpers without executing the Streamlit application."""
    source = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    names = {"decimal_default", "safe_json_dumps", "context_fingerprint", "safe_upload_name", "result_state"}
    nodes = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = dict(Decimal=Decimal, datetime=datetime, date=date, json=json, hashlib=hashlib, Path=Path)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app_helpers", "exec"), namespace)
    return namespace


def test_json_preserves_exact_decimal():
    helpers = app_helpers()
    amount = Decimal("123456789012345.123456")
    result = json.loads(helpers["safe_json_dumps"]({"amount": amount}))
    assert result["amount"] == str(amount)


def test_context_fingerprint_scopes_entity_and_database_without_exposing_secrets():
    helper = app_helpers().get("context_fingerprint")
    assert callable(helper), "UI must invalidate previews when their accounting/database context changes"
    config = {"host": "localhost", "database": "billing", "password": "sensitive"}
    current = helper("A", "真实文件处理", True, "mysql", config)
    assert current != helper("B", "真实文件处理", True, "mysql", config)
    assert current != helper("A", "真实文件处理", True, "mysql", {**config, "database": "other"})
    assert "sensitive" not in current


def test_upload_name_cannot_escape_staging_directory():
    helper = app_helpers().get("safe_upload_name")
    assert callable(helper), "Uploaded names must be sanitized before constructing staging paths"
    assert helper("../../invoice.pdf", 2) == "002-invoice.pdf"
    assert helper("C:\\private\\invoice.pdf", 3) == "003-invoice.pdf"


@pytest.mark.parametrize("result, expected", [
    ({"preview_only": True, "committed": False}, "preview"),
    ({"committed": True, "summary": {"operations": {"PENDING_REVIEW": 0}}}, "committed"),
    ({"committed": True, "summary": {"operations": {"PENDING_REVIEW": 1}}}, "partial"),
    ({"processing_results": [], "run_report": {"files_failed": 1}}, "failed"),
    ({"processing_results": [], "run_report": {"file_errors": [{"section": "model", "error": "invalid JSON"}]}}, "failed"),
    ({"preview_only": False, "committed": False, "summary": {"operations": {"PENDING_REVIEW": 1}}}, "pending"),
    ({"committed": True, "processing_results": [{"operation": "CREATE"}],
      "run_report": {"file_errors": [{"reviewable": True, "acknowledged": True, "review_note": "仅为商标"}]}}, "committed"),
])
def test_status_does_not_claim_failed_or_preview_work_was_persisted(result, expected):
    helper = app_helpers().get("result_state")
    assert callable(helper), "Preview, committed, pending and failed states must be distinguished"
    assert helper(result) == expected


def test_app_configures_d_drive_runtime_before_third_party_imports():
    source = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    configure_line = next((node.lineno for node in source.body
                           if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                           and isinstance(node.value.func, ast.Name)
                           and node.value.func.id == "configure_runtime"), None)
    streamlit_line = next(node.lineno for node in source.body
                          if isinstance(node, ast.Import) and any(alias.name == "streamlit" for alias in node.names))
    assert configure_line is not None and configure_line < streamlit_line


def test_app_guards_streamlit_global_storage_before_using_ui():
    source = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    streamlit_index = next(index for index, node in enumerate(source.body)
                           if isinstance(node, ast.Import) and any(alias.name == "streamlit" for alias in node.names))
    guard = source.body[streamlit_index + 1]
    assert isinstance(guard, ast.Expr) and isinstance(guard.value, ast.Call)
    assert isinstance(guard.value.func, ast.Name) and guard.value.func.id == "configure_streamlit_storage"
    readme = (ROOT / "README.md").read_text(encoding="utf-8-sig")
    assert "raise SystemExit(launch_streamlit())" in readme


def test_default_pytest_collection_excludes_live_service_scripts():
    config = ROOT / "pytest.ini"
    assert config.exists(), "pytest must not collect root-level scripts that call real databases/models"
    assert "testpaths = tests" in config.read_text(encoding="utf-8-sig")


def test_demo_rerun_does_not_reexecute_workflow(monkeypatch):
    """A download/widget rerun must display the saved result rather than run again."""
    import dotenv
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("DB_TYPE", "sqlite")
    monkeypatch.setenv("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    calls = []

    class FakeWorkflow:
        def __init__(self, **kwargs):
            self.accounting_entity = kwargs["accounting_entity"]

        def process_demo_scenario(self, scenario_name, output_dir=None):
            calls.append(scenario_name)
            return {
                "preview_id": "offline-demo", "preview_only": True, "committed": False,
                "processing_results": [], "source_documents": [],
                "ledger_snapshot": {"ledger_id": "test", "accounting_entity": self.accounting_entity, "records": []},
                "summary": {"operations": {"CREATE": 0, "UPDATE": 0, "NO_CHANGE": 0, "PENDING_REVIEW": 0}},
                "run_report": {"files_failed": 0},
            }

        def close(self):
            pass

    workflow_module = types.ModuleType("billing_agent.workflow")
    workflow_module.BillingWorkflow = FakeWorkflow
    db_module = types.ModuleType("billing_agent.workflow_db")
    db_module.DatabaseWorkflow = FakeWorkflow
    monkeypatch.setitem(sys.modules, "billing_agent.workflow", workflow_module)
    monkeypatch.setitem(sys.modules, "billing_agent.workflow_db", db_module)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
    assert not app.exception
    app.button(key="btn_update").click().run()
    assert not app.exception
    assert calls == ["update"]
    app.run()
    assert not app.exception
    assert calls == ["update"]
    app.text_input(key="accounting_entity").set_value("Another entity").run()
    assert not app.exception
    assert "billing_result" not in app.session_state
    assert calls == ["update"]


@pytest.mark.parametrize("amount_text", ["40.00", ""])
def test_partial_commit_keeps_unresolved_review_available(monkeypatch, amount_text):
    import dotenv
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    submissions = []
    result = {
        "preview_id": "pending-demo", "preview_only": True, "committed": False,
        "processing_results": [{
            "item_id": "item-1", "operation": "PENDING_REVIEW",
            "charge_details": {"original_name": "HANDLING", "amount": "40.00", "currency": "USD"},
            "candidates": [{"record_id": "OLD", "charge_details": {"original_name": "HANDLING", "amount": "35.00", "currency": "USD"}, "document_info": {"document_number": "D1"}}],
        }],
        "summary": {"operations": {"PENDING_REVIEW": 1}}, "run_report": {},
        "ledger_snapshot": {"records": []},
    }

    class FakeWorkflow:
        def __init__(self, **kwargs):
            pass

        def process_demo_scenario(self, *args):
            return result

        def commit_preview(self, preview_id, review_actions=None):
            submissions.append((preview_id, review_actions))
            return {**result, "preview_only": False, "committed": True}

    workflow_module = types.ModuleType("billing_agent.workflow")
    workflow_module.BillingWorkflow = FakeWorkflow
    db_module = types.ModuleType("billing_agent.workflow_db")
    db_module.DatabaseWorkflow = FakeWorkflow
    monkeypatch.setitem(sys.modules, "billing_agent.workflow", workflow_module)
    monkeypatch.setitem(sys.modules, "billing_agent.workflow_db", db_module)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
    app.button(key="btn_update").click().run()
    app.selectbox(key="review_target_pending-demo_item-1").set_value("OLD")
    app.text_input(key="review_amount_pending-demo_item-1").set_value(amount_text)
    app.text_area(key="review_note_pending-demo_item-1").set_value("已核对原始费用行")
    app.checkbox(key="commit_ack_pending-demo").check()
    submit = next(button for button in app.button if button.label == "提交已通过校验的变更")
    submit.click().run()
    assert not app.exception
    assert submissions[0][1]["item-1"]["record_id"] == "OLD"
    assert submissions[0][1]["item-1"]["amount"] == amount_text
    assert any(button.label == "提交已通过校验的变更" for button in app.button)


@pytest.mark.parametrize("note", ["", "已查看内嵌图片，确认仅为公司标志，无费用信息"])
def test_only_reviewable_source_errors_can_be_excluded_with_human_note(monkeypatch, note):
    import dotenv
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    submissions = []
    result = {
        "preview_id": "source-preview", "preview_only": True, "committed": False,
        "processing_results": [], "summary": {"operations": {}}, "ledger_snapshot": {"records": []},
        "run_report": {"file_errors": [
            {"file": "logo.png", "error": "OCR unavailable", "reviewable": True},
            {"section": "model", "error": "invalid JSON", "reviewable": False},
        ]},
    }

    class FakeWorkflow:
        def __init__(self, **kwargs):
            pass

        def process_demo_scenario(self, *args):
            return result

        def commit_preview(self, preview_id, review_actions=None):
            submissions.append(review_actions)
            errors = [dict(error) for error in result["run_report"]["file_errors"]]
            errors[0].update(acknowledged=True, review_note=review_actions["__source_reviews__"][0]["note"])
            return {**result, "run_report": {"file_errors": errors}}

    workflow_module = types.ModuleType("billing_agent.workflow")
    workflow_module.BillingWorkflow = FakeWorkflow
    db_module = types.ModuleType("billing_agent.workflow_db")
    db_module.DatabaseWorkflow = FakeWorkflow
    monkeypatch.setitem(sys.modules, "billing_agent.workflow", workflow_module)
    monkeypatch.setitem(sys.modules, "billing_agent.workflow_db", db_module)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
    app.button(key="btn_update").click().run()
    assert not app.exception
    source_checks = [element for element in app.checkbox if str(element.key).startswith("review_source_exclude_")]
    assert len(source_checks) == 1
    source_checks[0].check()
    app.text_area(key="review_source_note_source-preview_0").set_value(note)
    app.checkbox(key="commit_ack_source-preview").check()
    next(button for button in app.button if button.label == "提交已通过校验的变更").click().run()
    assert not app.exception
    if note:
        assert submissions == [{"__source_reviews__": [{"issue_index": 0, "exclude": True, "note": note}]}]
        assert any(note in caption.value for caption in app.caption)
    else:
        assert submissions == []
        assert any("来源" in warning.value and "依据" in warning.value for warning in app.warning)
