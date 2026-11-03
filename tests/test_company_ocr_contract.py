"""The assignment supplies a URL-based OCR API, not a separate vision model."""
from pathlib import Path

import pytest
from PIL import Image

from src.billing_agent.database import DatabaseManager
from src.billing_agent.integrations import OCRAdapter
from src.billing_agent.parsers import DocumentParser, OCRProcessingError
from src.billing_agent.workflow_db import DatabaseWorkflow


def test_company_ocr_is_default_without_a_vision_model(monkeypatch):
    monkeypatch.delenv("OCR_BACKEND", raising=False)
    monkeypatch.delenv("VISION_MODEL", raising=False)
    monkeypatch.setenv("OCR_URL", "https://gateway.pltplt.com/ai/process")
    db = DatabaseManager("sqlite", {"database": ":memory:"})
    flow = DatabaseWorkflow("A", db_manager=db, agent=object())
    try:
        flow._initialize_services()
        assert flow.parser.ocr_backend == "remote"
        assert flow.parser.vision_adapter is None
        assert flow.parser.ocr_adapter.url == "https://gateway.pltplt.com/ai/process"
    finally:
        flow.close()


def test_default_and_explicit_company_backend_have_same_processing_signature(monkeypatch):
    monkeypatch.delenv("OCR_BACKEND", raising=False)
    default = DatabaseWorkflow._signature()
    monkeypatch.setenv("OCR_BACKEND", "remote")
    assert default == DatabaseWorkflow._signature()


def test_company_request_matches_the_provided_example(monkeypatch):
    from src.billing_agent import integrations
    monkeypatch.setenv("OCR_URL", "https://gateway.pltplt.com/ai/process")
    monkeypatch.delenv("OCR_TOKEN", raising=False)
    captured = []
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"data": {"text": "HANDLING USD 40"}}
    def post(url, **kwargs):
        captured.append((url, kwargs))
        return Response()
    monkeypatch.setattr(integrations.requests, "post", post)
    result = OCRAdapter().process_file("https://files.example/bill.pdf")
    assert result["data"]["text"] == "HANDLING USD 40"
    assert captured[0][0] == "https://gateway.pltplt.com/ai/process"
    assert captured[0][1]["json"] == {"file": "https://files.example/bill.pdf", "task": "orderChange",
                                      "callBack": "", "taskType": ""}
    assert captured[0][1]["headers"] == {}


class NoStorage:
    def is_configured(self):
        return False
    def upload_file(self, *args):
        raise AssertionError("No upload may be invented")


class CompanyOCR:
    def __init__(self):
        self.calls = []
    def process_file(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return {"data": {"text": "HANDLING USD 40"}}


def test_known_file_url_uses_company_ocr_without_oss(tmp_path):
    ocr = CompanyOCR()
    parser = DocumentParser(ocr_enabled=True, ocr_backend="remote", ocr_adapter=ocr,
                            oss_adapter=NoStorage(), work_dir=tmp_path)
    result = parser.parse_file_from_url("https://files.example/bill.pdf")
    assert result["content"] == "HANDLING USD 40"
    assert ocr.calls == [("https://files.example/bill.pdf", {"task": "orderChange"})]
    assert Path(result["metadata"]["observation_path"]).is_file()


def test_local_image_reports_missing_file_url_instead_of_requiring_vision(tmp_path):
    path = tmp_path / "bill.png"
    Image.new("RGB", (20, 20), "white").save(path)
    ocr = CompanyOCR()
    parser = DocumentParser(ocr_enabled=True, ocr_backend="remote", ocr_adapter=ocr,
                            oss_adapter=NoStorage(), work_dir=tmp_path)
    with pytest.raises(OCRProcessingError) as caught:
        parser.parse_file(path)
    issues = caught.value.metadata["errors"]
    assert issues[0]["metadata"]["code"] == "OCR_FILE_URL_REQUIRED"
    assert "可访问" in issues[0]["error"]
    assert "VISION_MODEL" not in issues[0]["error"]
    assert ocr.calls == []
