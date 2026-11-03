"""Offline parser regression tests; every artifact stays inside the D-drive project."""
import hashlib
import json
import os
import tempfile
from email.message import EmailMessage
from pathlib import Path


def test_streamlit_disk_cache_alias_is_redirected_with_global_helper(monkeypatch):
    import sys
    from types import SimpleNamespace
    from src.billing_agent.runtime import CACHE_DIR, configure_streamlit_storage
    original = lambda *parts: str(Path("C:/uncontrolled") / Path(*parts))
    utility = SimpleNamespace(get_streamlit_file_path=original)
    cache_module = SimpleNamespace(get_streamlit_file_path=original)
    monkeypatch.setitem(sys.modules, "streamlit.runtime.caching.storage.local_disk_cache_storage", cache_module)
    configure_streamlit_storage(utility)
    assert Path(cache_module.get_streamlit_file_path("cache")).is_relative_to(CACHE_DIR)

import pytest
from PIL import Image

from src.billing_agent.parsers import DocumentParser


PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def work():
    root = PROJECT / "output" / "test-temp"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as folder:
        yield Path(folder)


class FakeOSS:
    def __init__(self, cleanup_error=False):
        self.uploaded = []
        self.deleted = []
        self.cleanup_error = cleanup_error

    def is_configured(self):
        return True

    def upload_file(self, path, name):
        assert Path(path).is_file()
        self.uploaded.append(name)
        return "https://example.invalid/object?signature=secret"

    def delete_file(self, name):
        if self.cleanup_error:
            raise RuntimeError("delete failed")
        self.deleted.append(name)


class FakeOCR:
    def __init__(self, response=None, error=None):
        self.response = response if response is not None else {
            "code": 0, "data": [{"text": "HANDLING CHARGE USD 35.00"}]
        }
        self.error = error
        self.calls = []

    def process_file(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def image_file(work, name="bill.png"):
    path = work / name
    Image.new("RGB", (10, 10), "white").save(path)
    return path


def test_runtime_redirects_temp_and_configurable_cache_to_project():
    from src.billing_agent.runtime import configure_runtime, ROOT_DIR, TEMP_DIR, LOG_DIR
    configure_runtime()
    assert ROOT_DIR == PROJECT
    assert TEMP_DIR.is_relative_to(PROJECT)
    assert LOG_DIR.is_relative_to(PROJECT)
    for key in ("TEMP", "TMP", "TMPDIR", "XDG_CACHE_HOME", "MPLCONFIGDIR"):
        assert Path(os.environ[key]).resolve().is_relative_to(PROJECT)
    assert Path(tempfile.gettempdir()).resolve() == TEMP_DIR


def test_image_upload_really_calls_ocr_and_keeps_raw_result(work):
    oss, ocr = FakeOSS(), FakeOCR()
    path = image_file(work)
    parsed = DocumentParser(True, ocr, oss, work).parse_file(path)
    assert len(ocr.calls) == 1
    assert len(oss.uploaded) == 1
    assert oss.deleted == oss.uploaded
    assert "35.00" in parsed["content"]
    assert parsed["metadata"]["ocr_processed"] is True
    assert parsed["metadata"]["ocr_raw"] == ocr.response
    assert parsed["source_id"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert parsed["blocks"][0]["source_id"] == parsed["source_id"]
    assert parsed["blocks"][0]["block_id"]
    assert parsed["errors"] == []


def test_same_filename_uses_distinct_cloud_objects(work):
    oss, ocr = FakeOSS(), FakeOCR()
    parser = DocumentParser(True, ocr, oss, work)
    path = image_file(work)
    parser.parse_file(path)
    parser.parse_file(path)
    assert len(set(oss.uploaded)) == 2


@pytest.mark.parametrize("filename", ["001-图片示例.png", "invoice%20(final).PNG"])
def test_ocr_upload_uses_ascii_name_and_preserves_original_filename(work, filename):
    oss = FakeOSS()
    parsed = DocumentParser(True, FakeOCR(), oss, work).parse_file(image_file(work, filename))
    key = oss.uploaded[0]
    assert key.isascii() and "%" not in key
    assert Path(key).suffix == ".png"
    assert parsed["source_file"] == filename
    assert parsed["metadata"]["original_filename"] == filename
    assert oss.deleted == [key]


def test_image_without_ocr_fails_instead_of_returning_placeholder(work):
    with pytest.raises(ValueError, match="OCR"):
        DocumentParser(work_dir=work).parse_file(image_file(work))


@pytest.mark.parametrize("response", [
    {"code": 400, "message": "bad file"},
    {"code": 0, "data": {"text": ""}},
    {"success": False, "code": 0, "data": {"text": "unexpected"}},
])
def test_ocr_business_error_or_empty_text_is_not_success(work, response):
    oss = FakeOSS()
    with pytest.raises(ValueError):
        DocumentParser(True, FakeOCR(response), oss, work).parse_file(image_file(work))
    assert oss.deleted == oss.uploaded


def test_timeout_keeps_object_and_persists_cleanup_pending(work):
    oss = FakeOSS()
    with pytest.raises(ValueError) as exc:
        DocumentParser(True, FakeOCR(error=TimeoutError("timeout")), oss, work).parse_file(image_file(work))
    assert oss.deleted == []
    assert getattr(exc.value, "metadata", {}).get("cleanup_pending") is True
    assert list((work / "cleanup-pending").glob("*.json"))


def test_cleanup_failure_is_visible_in_result(work):
    parsed = DocumentParser(True, FakeOCR(), FakeOSS(True), work).parse_file(image_file(work))
    assert parsed["metadata"]["cleanup_pending"] is True
    assert any(error["code"] == "cleanup_pending" for error in parsed["errors"])


def test_eml_prefers_plain_and_parses_attachment_with_source_link(work):
    message = EmailMessage()
    message["Subject"] = "PRE-ALERT"
    message.set_content("BODY FEE USD 50")
    message.add_alternative("<html><body>HTML DUPLICATE USD 50</body></html>", subtype="html")
    message.add_attachment(b"ATTACHMENT FEE USD 35", maintype="text", subtype="plain", filename="../../bill.txt")
    path = work / "mail.eml"
    path.write_bytes(message.as_bytes())
    parsed = DocumentParser(work_dir=work).parse_file(path)
    assert "BODY FEE" in parsed["content"]
    assert "HTML DUPLICATE" not in parsed["content"]
    assert "ATTACHMENT FEE USD 35" in parsed["content"]
    assert any(block["block_id"].endswith("email-header:subject")
               and block["text"] == "Subject: PRE-ALERT" for block in parsed["blocks"])
    attachment = parsed["attachments"][0]
    assert attachment["parent_source_id"] == parsed["source_id"]
    assert attachment["source_id"] != parsed["source_id"]
    assert Path(attachment["archive_path"]).resolve().is_relative_to(work)
    assert ".." not in Path(attachment["archive_path"]).name
    assert any(block["source_id"] == attachment["source_id"] for block in parsed["blocks"])


def test_unsupported_email_attachment_surfaces_error(work):
    message = EmailMessage()
    message.set_content("BODY USD 50")
    message.add_attachment(b"unknown", maintype="application", subtype="octet-stream", filename="bill.xyz")
    path = work / "mail.eml"
    path.write_bytes(message.as_bytes())
    parsed = DocumentParser(work_dir=work).parse_file(path)
    assert parsed["errors"]
    assert parsed["attachments"][0]["status"] == "failed"


def test_text_has_stable_source_blocks_and_empty_text_fails(work):
    path = work / "bill.txt"
    path.write_text("HANDLING USD 50\nTOTAL USD 50", encoding="utf-8")
    parser = DocumentParser(work_dir=work)
    parsed = parser.parse_file(path)
    assert parsed["blocks"][0]["row"] == 1
    assert parsed["source_id"] == parser.parse_file(path)["source_id"]
    path.write_text("  \n", encoding="utf-8")
    with pytest.raises(ValueError):
        parser.parse_file(path)


def test_ocr_adapter_sends_token_without_logging_secret_url(monkeypatch, caplog):
    from src.billing_agent.integrations import OCRAdapter
    monkeypatch.setenv("OCR_URL", "https://example.invalid/ocr")
    monkeypatch.setenv("OCR_TOKEN", "never-log-this-token")
    monkeypatch.setenv("OCR_TOKEN_HEADER", "X-API-Key")
    captured = {}
    class Response:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"code": 0, "data": {"text": "FEE 50"}}
    def post(url, **kwargs):
        captured.update(kwargs)
        return Response()
    monkeypatch.setattr("src.billing_agent.integrations.requests.post", post)
    result = OCRAdapter().process_file("https://example.invalid/a?signature=never-log-this-signature")
    assert result["code"] == 0
    assert "headers" in captured
    assert captured["headers"]["X-API-Key"] == "never-log-this-token"
    assert "never-log-this-token" not in caplog.text
    assert "never-log-this-signature" not in caplog.text


def make_pdf(work, text_first_page=None):
    from PyPDF2 import PdfWriter
    from PyPDF2.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    if text_first_page:
        writer.add_blank_page(width=300, height=300)
        page = writer.pages[-1]
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 20 250 Td ({text_first_page}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_blank_page(width=300, height=300)
    path = work / "mixed.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def test_mixed_pdf_ocr_reads_missing_page_and_preserves_page_identity(work):
    ocr, oss = FakeOCR(), FakeOSS()
    parsed = DocumentParser(True, ocr, oss, work).parse_file(
        make_pdf(work, "VISIBLE FIRST PAGE CHARGE USD 65.00"))
    assert len(ocr.calls) == 1
    assert {block["page"] for block in parsed["blocks"]} == {1, 2}
    assert "VISIBLE FIRST PAGE" in parsed["content"]
    assert "35.00" in parsed["content"]
    assert parsed["metadata"]["ocr_raw"][0]["page"] == 2
    assert not list((work / "ocr-pages").glob("*.pdf"))


def test_all_scanned_pdf_failure_retains_error_metadata(work):
    with pytest.raises(ValueError) as exc:
        DocumentParser(True, FakeOCR(error=TimeoutError()), FakeOSS(), work).parse_file(make_pdf(work))
    assert getattr(exc.value, "metadata", {}).get("errors")
    assert exc.value.metadata["errors"][0]["metadata"]["cleanup_pending"] is True


def test_inline_image_is_analyzed_instead_of_silently_ignored(work):
    message = EmailMessage()
    message.set_content("BODY USD 50")
    message.add_alternative("<html><img src='cid:invoice'></html>", subtype="html")
    html_part = message.get_payload()[1]
    html_part.add_related(image_file(work).read_bytes(), maintype="image", subtype="png",
                          cid="invoice", filename="bill.png", disposition="inline")
    path = work / "inline.eml"
    path.write_bytes(message.as_bytes())
    parsed = DocumentParser(True, FakeOCR(), FakeOSS(), work).parse_file(path)
    assert parsed["attachments"]
    assert "35.00" in parsed["content"]


def test_nested_email_attachment_is_parsed(work):
    nested = EmailMessage()
    nested.set_content("NESTED FEE USD 20")
    message = EmailMessage()
    message.set_content("OUTER BODY USD 50")
    message.add_attachment(nested, filename="forwarded.eml")
    path = work / "nested.eml"
    path.write_bytes(message.as_bytes())
    parsed = DocumentParser(work_dir=work).parse_file(path)
    assert "NESTED FEE USD 20" in parsed["content"]


def test_structured_logs_redact_credentials_and_url_query(caplog):
    from src.billing_agent.logger_config import get_workflow_logger, log_dict
    log_dict(get_workflow_logger(), {"password": "password-value-never-log",
                                   "api_key": "api-key-never-log",
                                   "file": "https://example.invalid/a?signature=query-never-log"})
    assert "password-value-never-log" not in caplog.text
    assert "api-key-never-log" not in caplog.text
    assert "query-never-log" not in caplog.text


def test_streamlit_storage_helper_redirects_only_streamlit_files():
    from types import SimpleNamespace
    from src.billing_agent.runtime import configure_streamlit_storage
    helper = SimpleNamespace(get_streamlit_file_path=lambda *parts: str(Path("C:/old") / Path(*parts)))
    configure_streamlit_storage(helper)
    path = Path(helper.get_streamlit_file_path("credentials.toml"))
    assert path.is_relative_to(PROJECT / "output")
    assert path.name == "credentials.toml"


def test_start_script_bootstraps_runtime_before_streamlit():
    script = (PROJECT / "start.bat").read_text(encoding="utf-8")
    assert 'cd /d "%~dp0"' in script.lower()
    assert "billing_agent.runtime import launch_streamlit" in script
    assert "streamlit run app.py" not in script


def test_long_names_archive_to_short_distinct_paths_and_preserve_original_names(work):
    prefix = "invoice-" + "x" * 110
    first, second = work / f"{prefix}-A.txt", work / f"{prefix}-B.txt"
    first.write_text("HANDLING USD 35", encoding="utf-8")
    second.write_text("HANDLING USD 65", encoding="utf-8")
    parser = DocumentParser(work_dir=work)
    a, b = parser.parse_file(first), parser.parse_file(second)
    archive_a, archive_b = Path(a["metadata"]["archive_path"]), Path(b["metadata"]["archive_path"])
    assert len(str(archive_a)) < 260
    assert archive_a != archive_b
    assert archive_a.suffix == archive_b.suffix == ".txt"
    assert a["source_file"] == first.name and b["source_file"] == second.name
    assert archive_a.read_bytes() == first.read_bytes()
    assert archive_b.read_bytes() == second.read_bytes()


def test_parse_observation_keeps_raw_ocr_on_disk_without_overwriting_reparse(work):
    ocr = FakeOCR({"code": 0, "data": {"text": "INVOICE FEE USD 35", "recognition_id": "raw-1"}})
    parser = DocumentParser(True, ocr, FakeOSS(), work)
    image = image_file(work)
    first = parser.parse_file(image)
    assert first["metadata"].get("observation_path")
    observation = Path(first["metadata"]["observation_path"])
    saved_bytes = observation.read_bytes()
    payload = json.loads(saved_bytes)
    assert payload["source_id"] == first["source_id"]
    assert payload["blocks"] == first["blocks"]
    assert payload["metadata"]["ocr_raw"] == ocr.response
    assert payload["errors"] == []
    second = parser.parse_file(image)
    assert second["metadata"]["observation_path"] != str(observation)
    assert observation.read_bytes() == saved_bytes
    assert Path(second["metadata"]["observation_path"]).is_file()
    assert observation.is_relative_to(work / "observations")
    assert len(str(observation)) < 260


def test_partial_parse_observation_preserves_errors_and_attachment_refs(work):
    message = EmailMessage()
    message.set_content("HANDLING USD 50")
    message.add_attachment(b"unreadable", maintype="application", subtype="octet-stream", filename="bill.unknown")
    path = work / "mail.eml"
    path.write_bytes(message.as_bytes())
    parsed = DocumentParser(work_dir=work).parse_file(path)
    assert parsed["metadata"].get("observation_path")
    saved = json.loads(Path(parsed["metadata"]["observation_path"]).read_text(encoding="utf-8"))
    assert saved["errors"] == parsed["errors"]
    assert saved["attachments"][0]["source_id"] == parsed["attachments"][0]["source_id"]
    assert Path(saved["attachments"][0]["archive_path"]).is_file()
