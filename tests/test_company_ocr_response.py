"""The company's live API returns structured list/chargeList, not a text field."""
from email.message import EmailMessage
from pathlib import Path
import json
import io
import pytest

from PIL import Image

from src.billing_agent.parsers import DocumentParser, OCRProcessingError


def company_result():
    return {"success": True, "message": "文档处理成功", "data": {
        "createDate": "2026-11-03", "fileName": "", "orderType": "None", "pages_split": [[0]],
        "list": [{"invoiceNumber": "INV-100", "consignee": "TEST CUSTOMER", "mblNumber": "BL-100",
                  "chargeList": [{"chargeItem": "WHARFAGE", "amount": "5.00", "chargeCtr": ""},
                                 {"chargeItem": "OTHER FEE", "amount": "0", "currency": "JPY"}],
                  "other": [], "page_index": [0]}]}}


class OCR:
    def process_file(self, url, **kwargs):
        return company_result()


class Storage:
    def __init__(self):
        self.deleted = []
    def is_configured(self):
        return True
    def upload_file(self, path, name):
        return "https://test.example/file.png"
    def delete_file(self, name):
        self.deleted.append(name)


def test_company_structured_response_retains_invoice_and_charge_values(tmp_path):
    parser = DocumentParser(work_dir=tmp_path)
    text = parser._extract_ocr_text(company_result())
    assert "INV-100" in text and "BL-100" in text
    assert "WHARFAGE" in text and "5.00" in text
    assert "OTHER FEE" in text and "JPY" in text
    assert "USD" not in text  # Company did not supply USD; never manufacture it.
    assert "chargeList" in text


def test_observed_live_company_invoice_response_is_supported(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "company_ocr_zim_observed.json"
    response = json.loads(fixture.read_text(encoding="utf-8"))
    text = DocumentParser(work_dir=tmp_path)._extract_ocr_text(response)
    assert "ORFR1618731" in text
    assert "WHARFAGE ADMINISTRATION FEE" in text and "5.00" in text
    assert "WHARFAGE" in text and "21.90" in text
    assert "USD" not in text


def test_company_empty_success_is_not_business_text(tmp_path):
    parser = DocumentParser(work_dir=tmp_path)
    response = {"success": True, "data": {"createDate": "today", "list": [], "pages_split": [], "orderType": "None"}}
    assert parser._extract_ocr_text(response) == ""


def test_company_empty_success_explains_upstream_empty_result_and_keeps_response(tmp_path):
    raw = {"success": True, "data": {"list": [], "pages_split": []}}
    class EmptyOCR:
        def process_file(self, *args, **kwargs):
            return raw
    path = tmp_path / "image.png"
    Image.new("RGB", (20, 20), "white").save(path)
    storage = Storage()
    parser = DocumentParser(True, EmptyOCR(), storage, tmp_path)
    with pytest.raises(OCRProcessingError) as caught:
        parser.parse_file(path)
    assert caught.value.metadata["code"] == "OCR_EMPTY_RESULT"
    assert "公司OCR" in str(caught.value) and "为空" in str(caught.value)
    assert caught.value.metadata["ocr_raw"] == raw
    assert storage.deleted


def test_local_image_with_company_response_is_parsed_and_raw_is_preserved(tmp_path):
    path = tmp_path / "invoice.png"
    Image.new("RGB", (20, 20), "white").save(path)
    storage = Storage()
    parser = DocumentParser(ocr_enabled=True, ocr_backend="remote", ocr_adapter=OCR(),
                            oss_adapter=storage, work_dir=tmp_path)
    parsed = parser.parse_file(path)
    assert "WHARFAGE" in parsed["content"]
    assert parsed["metadata"]["ocr_raw"] == company_result()
    assert parsed["metadata"]["ocr_content_type"] == "company_structured_fields"
    assert storage.deleted
    assert parsed["errors"] == []


def test_url_company_response_needs_no_storage(tmp_path):
    parser = DocumentParser(ocr_enabled=True, ocr_backend="remote", ocr_adapter=OCR(), work_dir=tmp_path)
    parsed = parser.parse_file_from_url("https://test.example/invoice.png", "image")
    assert "INV-100" in parsed["content"]
    assert parsed["metadata"]["ocr_content_type"] == "company_structured_fields"


def test_eml_inline_image_uses_company_structured_output(tmp_path):
    image = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(image, format="PNG")
    mail = EmailMessage()
    mail["Subject"] = "Synthetic test only"
    mail.set_content("Attached billing image")
    mail.add_attachment(image.getvalue(), maintype="image", subtype="png", filename="invoice.png")
    path = tmp_path / "mail.eml"
    path.write_bytes(mail.as_bytes())
    parser = DocumentParser(ocr_enabled=True, ocr_backend="remote", ocr_adapter=OCR(),
                            oss_adapter=Storage(), work_dir=tmp_path)
    parsed = parser.parse_file(path)
    assert "WHARFAGE" in parsed["content"]
    assert parsed["attachments"][0]["status"] == "success"
    assert parsed["errors"] == []
