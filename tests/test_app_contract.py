"""Offline UI contracts: preview lifecycle, exact amounts and safe uploads."""

import ast
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[1]


def app_helpers():
    """Load pure helpers without executing the Streamlit application."""
    source = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    names = {"decimal_default", "safe_json_dumps", "context_fingerprint", "safe_upload_name", "result_state",
             "issue_message", "issue_is_resolved", "issue_is_blocking", "recognition_settings"}
    nodes = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = dict(Decimal=Decimal, datetime=datetime, date=date, json=json, hashlib=hashlib, Path=Path, os=os)
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


@pytest.mark.parametrize("name", ["OCR_BACKEND", "VISION_MODEL", "VISION_BASE_URL", "VISION_API_KEY",
                                  "DEFAULT_POSTING_TYPE", "ALLOW_UNMAPPED_CHARGES"])
def test_context_fingerprint_invalidates_recognition_and_policy_changes(monkeypatch, name):
    helper = app_helpers()["context_fingerprint"]
    monkeypatch.setenv(name, "first-setting")
    before = helper("A", "real", True, "sqlite", {})
    monkeypatch.setenv(name, "second-setting")
    after = helper("A", "real", True, "sqlite", {})
    assert before != after
    assert "second-setting" not in after


def test_resolved_historical_parser_failure_does_not_make_committed_result_partial():
    helper = app_helpers()["result_state"]
    result = {"committed": True, "summary": {"operations": {"PENDING_REVIEW": 0}},
              "run_report": {"processing_status": "COMMITTED", "files_failed": 1,
                             "file_errors": [{"error": "旧附件失败已确认无关", "acknowledged": True}]}}
    assert helper(result) == "committed"


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
    ({"preview_only": True, "processing_results": [{"operation": "PENDING_REVIEW"}],
      "run_report": {"processing_status": "PROCESSING_FAILED", "file_errors": [
          {"origin": "parser", "error": "VISION_MODEL未配置"}]}}, "failed"),
    ({"committed": True, "processing_results": [],
      "run_report": {"processing_status": "PROCESSING_FAILED", "files_failed": 1}}, "partial"),
])
def test_status_does_not_claim_failed_or_preview_work_was_persisted(result, expected):
    helper = app_helpers().get("result_state")
    assert callable(helper), "Preview, committed, pending and failed states must be distinguished"
    assert helper(result) == expected


@pytest.mark.parametrize("issue", [
    {"description": "未知费用保留原名", "severity": "warning"},
    {"message": "已按规则补齐方向", "status": "resolved"},
    {"error": "方向缺失", "resolved_by_policy": "default-ar-v1"},
    {"message": "身份已补提取", "status": "resolved_by_reextraction"},
])
def test_warning_or_resolved_issue_does_not_mark_successful_commit_partial(issue):
    result = {"committed": True, "processing_results": [{"operation": "CREATE"}],
              "run_report": {"file_errors": [issue]}}
    assert app_helpers()["result_state"](result) == "committed"


def test_vision_configuration_reports_exact_missing_names_without_secrets():
    helper = app_helpers().get("recognition_settings")
    assert callable(helper), "UI must explain visual API configuration without requiring OSS"
    missing = helper({"OCR_BACKEND": "vision"})
    assert missing["configured"] is False
    assert "VISION_MODEL" in missing["missing"]
    assert any("VISION_API_KEY" in name for name in missing["missing"])
    assert any("VISION_BASE_URL" in name for name in missing["missing"])
    configured = helper({"OCR_BACKEND": "vision", "VISION_MODEL": "vision-test",
                         "VISION_API_KEY": "private-example-value", "VISION_BASE_URL": "https://vision.example/v1"})
    assert configured["configured"] is True
    assert configured["requires_oss"] is False
    assert "private-example-value" not in json.dumps(configured)
    assert helper({"OCR_BACKEND": "vision", "VISION_MODEL": "vision-test",
                   "DASHSCOPE_API_KEY": "text-provider-key", "QWEN_BASE_URL": "https://text.example/v1"})["configured"] is True


def test_company_ocr_configuration_separates_endpoint_from_local_file_transport():
    helper = app_helpers().get("recognition_settings")
    assert callable(helper), "Company OCR accepts a reachable file URL, not a local path"
    status = helper({"OCR_URL": "https://gateway.pltplt.com/ai/process"})
    assert status["backend"] == "remote"
    assert status["configured"] is True
    assert status["missing"] == []
    assert status["requires_file_url"] is True
    assert status["requires_oss"] is False
    assert status["local_files_ready"] is False
    missing = helper({})
    assert missing["missing"] == ["OCR_URL"]
    assert "VISION" not in json.dumps(missing)


def test_optional_oss_transport_can_supply_company_ocr_file_url():
    helper = app_helpers()["recognition_settings"]
    values = {"OCR_BACKEND": "remote", "OCR_URL": "https://gateway.pltplt.com/ai/process",
              "OSS_ACCESS_KEY_ID": "private-id", "OSS_ACCESS_KEY_SECRET": "private-secret",
              "OSS_ENDPOINT": "https://objects.example", "OSS_BUCKET": "test-bucket"}
    assert helper(values)["local_files_ready"] is True
    assert "private-secret" not in json.dumps(helper(values))
    values["OCR_URL"] = ""
    assert helper(values)["local_files_ready"] is False


def test_company_ocr_can_use_authorized_csv_without_copying_keys_to_env(tmp_path):
    path = tmp_path / "AccessKey.csv"
    path.write_text("AccessKey ID,AccessKey Secret\ntest-id,test-secret\n", encoding="utf-8-sig")
    helper = app_helpers()["recognition_settings"]
    config = {"OCR_URL": "https://gateway.pltplt.com/ai/process", "OSS_CREDENTIALS_FILE": str(path),
              "OSS_ENDPOINT": "https://oss-cn-shanghai.aliyuncs.com", "OSS_BUCKET": "ocr-phy"}
    status = helper(config)
    assert status["local_files_ready"] is True
    assert "test-secret" not in json.dumps(status)


def test_preview_context_changes_when_csv_credentials_are_rotated(tmp_path, monkeypatch):
    path = tmp_path / "AccessKey.csv"
    path.write_text("AccessKey ID,AccessKey Secret\nfirst-id,first-secret\n", encoding="utf-8")
    monkeypatch.setenv("OSS_CREDENTIALS_FILE", str(path))
    helper = app_helpers()["context_fingerprint"]
    before = helper("A", "real", True, "sqlite", {})
    path.write_text("AccessKey ID,AccessKey Secret\nsecond-id,second-secret\n", encoding="utf-8")
    after = helper("A", "real", True, "sqlite", {})
    assert before != after


def test_company_ocr_ui_without_visual_api_explains_local_file_url_gap(monkeypatch):
    import dotenv
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    for name in ("OCR_BACKEND", "VISION_MODEL", "VISION_API_KEY", "VISION_BASE_URL", "OSS_ACCESS_KEY_ID",
                 "OSS_ACCESS_KEY_SECRET", "OSS_ENDPOINT", "OSS_BUCKET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OCR_URL", "https://gateway.pltplt.com/ai/process")
    monkeypatch.setenv("DB_TYPE", "sqlite")
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
    app.radio(key="processing_mode").set_value("真实文件处理").run()
    assert not app.exception
    warnings = "\n".join(item.value for item in app.warning)
    assert "文件 URL" in warnings
    assert "VISION_MODEL" not in warnings
    assert "视觉API" not in warnings
    assert any("公司 OCR" in caption.value for caption in app.caption)


def test_issue_message_preserves_description_and_resolved_status():
    helpers = app_helpers()
    message = helpers.get("issue_message")
    blocks = helpers.get("issue_is_blocking")
    assert callable(message) and callable(blocks), "Issue rendering needs normalized messages and severity"
    assert message({"description": "视觉模型尚未配置"}) == "视觉模型尚未配置"
    assert message({"error": "", "message": "金额合计不一致"}) == "金额合计不一致"
    assert blocks({"description": "缺少来源证据"}) is True
    assert blocks({"description": "使用缺省 AR", "status": "resolved_by_policy"}) is False


@pytest.mark.parametrize("origin, expected_origin", [("default", "缺省"), ("model_inferred", "模型推断")])
def test_ui_keeps_description_and_separates_recognition_failures_from_warnings(monkeypatch, origin, expected_origin):
    import dotenv
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    result = {
        "preview_id": "classified", "preview_only": True,
        "summary": {"operations": {"CREATE": 1}},
        "processing_results": [{"operation": "CREATE", "charge_details": {
            "original_name": "原始费用", "amount": "245", "currency": "USD"},
            "financial_attributes": {"posting_type": "AR", "posting_type_origin": origin}}],
        "run_report": {"file_errors": [
            {"description": "请配置 VISION_MODEL", "origin": "parser", "code": "VISION_NOT_CONFIGURED"},
            {"description": "保留原始费用名称", "severity": "warning"},
            {"description": "方向已按规则解决", "status": "resolved_by_policy"},
        ]},
    }

    class FakeWorkflow:
        def __init__(self, **kwargs):
            pass

        def process_demo_scenario(self, *args):
            return result

    workflow_module = types.ModuleType("billing_agent.workflow")
    workflow_module.BillingWorkflow = FakeWorkflow
    db_module = types.ModuleType("billing_agent.workflow_db")
    db_module.DatabaseWorkflow = FakeWorkflow
    monkeypatch.setitem(sys.modules, "billing_agent.workflow", workflow_module)
    monkeypatch.setitem(sys.modules, "billing_agent.workflow_db", db_module)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
    app.button(key="btn_update").click().run()
    assert not app.exception
    red = "\n".join(item.value for item in app.error)
    assert "VISION_MODEL" in red
    assert "保留原始费用名称" not in red
    assert "方向已按规则解决" not in red
    assert any("保留原始费用名称" in item.value for item in app.warning)
    assert any("方向已按规则解决" in item.value for item in app.caption)
    assert any(expected_origin in item.value and "AR" in item.value for item in app.caption)


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
