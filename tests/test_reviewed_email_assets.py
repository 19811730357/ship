"""Only exact, reviewed non-billing assets can bypass OCR inside emails."""
from email.message import EmailMessage
import hashlib
import io

from PIL import Image

from src.billing_agent.parsers import DocumentParser
from .test_company_ocr_response import OCR, Storage


def image_bytes(color):
    stream = io.BytesIO()
    Image.new("RGB", (30, 20), color).save(stream, format="PNG")
    return stream.getvalue()


def email_file(tmp_path, raw):
    mail = EmailMessage()
    mail["Subject"] = "Invoice attachments"
    mail.set_content("Billing details in the attached documents.")
    mail.add_attachment(raw, maintype="image", subtype="png", filename="InsertPic.png")
    path = tmp_path / "invoice.eml"
    path.write_bytes(mail.as_bytes())
    return path


def reviewed(raw):
    return {hashlib.sha256(raw).hexdigest(): {"approved": True, "scope": "email_attachment",
        "reason": "Reviewed as a non-billing promotional banner", "reviewed_by": "test_review"}}


def test_reviewed_exact_email_asset_is_skipped_with_audit_not_an_error(tmp_path):
    raw = image_bytes("white")
    class NoOCR:
        def process_file(self, *args, **kwargs):
            raise AssertionError("Reviewed banner must not need another OCR request")
    parser = DocumentParser(ocr_enabled=True, ocr_backend="remote", ocr_adapter=NoOCR(),
        oss_adapter=Storage(), work_dir=tmp_path, non_billing_assets=reviewed(raw))
    parsed = parser.parse_file(email_file(tmp_path, raw))
    assert parsed["attachments"][0]["status"] == "skipped"
    assert all(issue.get("severity") == "warning" for issue in parsed["errors"])
    child = parsed["attachments"][0]["parsed"]
    assert child["metadata"]["asset_review"]["reviewed_by"] == "test_review"
    assert child["metadata"]["observation_path"]


def test_same_filename_with_different_image_bytes_still_uses_ocr(tmp_path):
    old, new = image_bytes("white"), image_bytes("black")
    parser = DocumentParser(ocr_enabled=True, ocr_backend="remote", ocr_adapter=OCR(),
        oss_adapter=Storage(), work_dir=tmp_path, non_billing_assets=reviewed(old))
    parsed = parser.parse_file(email_file(tmp_path, new))
    assert parsed["attachments"][0]["status"] == "success"
    assert "WHARFAGE" in parsed["content"]


def test_email_asset_review_does_not_skip_a_standalone_image(tmp_path):
    raw = image_bytes("white")
    path = tmp_path / "standalone.png"
    path.write_bytes(raw)
    parser = DocumentParser(ocr_enabled=True, ocr_backend="remote", ocr_adapter=OCR(),
        oss_adapter=Storage(), work_dir=tmp_path, non_billing_assets=reviewed(raw))
    parsed = parser.parse_file(path)
    assert "WHARFAGE" in parsed["content"]
    assert not parsed["metadata"].get("skipped")
