"""Offline local-image recognition; no cloud calls or C-drive artifacts."""
import base64
import inspect
import json
import tempfile
from email.message import EmailMessage
from pathlib import Path

import pytest
import requests
from PIL import Image

from src.billing_agent import integrations
from src.billing_agent.parsers import DocumentParser


PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def work():
    root = PROJECT / "output" / "test-temp"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as folder:
        yield Path(folder)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("VISION_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("VISION_MODEL", "test-vision")
    monkeypatch.setenv("VISION_API_KEY", "vision-test-secret")


def image_file(work, name="bill.png", color="white"):
    path = work / name
    Image.new("RGB", (30, 20), color).save(path)
    return path


def adapter():
    cls = getattr(integrations, "VisionOCRAdapter", None)
    assert cls is not None, "local vision adapter is not implemented"
    return cls()


class Response:
    def __init__(self, content, finish_reason="stop"):
        self.raw = {"id": "recognition-test", "choices": [{
            "finish_reason": finish_reason, "message": {"content": content}}]}

    def raise_for_status(self):
        pass

    def json(self):
        return self.raw


def recognition(text="HANDLING USD 35.00", **extra):
    return {"text": text, "provider": "vision", "model": "test-vision",
            "raw": {"request_id": "observation-test"}, **extra}


class FakeVision:
    def __init__(self, results=None, error=None):
        self.results = results or [recognition()]
        self.error = error
        self.calls = []

    def is_configured(self):
        return True

    def process_local_file(self, path):
        path = Path(path)
        assert path.is_file()
        with Image.open(path) as picture:
            picture.verify()
        self.calls.append(path)
        if self.error:
            raise self.error
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]


class UnusedOSS:
    def is_configured(self):
        pytest.fail("vision mode must not inspect OSS")


def parser(work, vision):
    assert "vision_adapter" in inspect.signature(DocumentParser).parameters, "vision parser routing is missing"
    return DocumentParser(ocr_enabled=True, vision_adapter=vision, ocr_backend="vision",
                          oss_adapter=UnusedOSS(), work_dir=work)


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


def test_vision_http_uses_local_base64_and_keeps_raw_without_logging_payload(work, configured, monkeypatch, caplog):
    picture = image_file(work)
    response = Response(json.dumps({"text": "HANDLING USD 35.00", "content_kind": "billing_document"}))
    captured = {}
    def post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return response
    monkeypatch.setattr(integrations.requests, "post", post)
    result = adapter().process_local_file(picture)
    assert captured["url"] == "https://example.invalid/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer vision-test-secret"
    assert captured["json"]["model"] == "test-vision"
    messages = captured["json"]["messages"]
    content = next(m["content"] for m in messages if m["role"] == "user")
    image = next(part["image_url"]["url"] for part in content if part["type"] == "image_url")
    assert image.startswith("data:image/png;base64,")
    assert base64.b64decode(image.split(",", 1)[1]) == picture.read_bytes()
    assert result["text"] == "HANDLING USD 35.00"
    assert result["raw"] == response.raw
    assert result["provider"] == "vision" and result["model"] == "test-vision"
    assert "vision-test-secret" not in caplog.text
    assert image not in caplog.text


def test_vision_configuration_falls_back_to_qwen_endpoint_and_key(configured, monkeypatch):
    monkeypatch.delenv("VISION_BASE_URL")
    monkeypatch.delenv("VISION_API_KEY")
    monkeypatch.setenv("QWEN_BASE_URL", "https://example.invalid/compatible-mode/v1")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fallback-test-key")
    client = adapter()
    assert client.is_configured() is True
    assert client.base_url == "https://example.invalid/compatible-mode/v1"


def test_missing_vision_model_is_not_configured_and_never_sends_http(work, configured, monkeypatch):
    monkeypatch.delenv("VISION_MODEL")
    monkeypatch.setattr(integrations.requests, "post", lambda *a, **kw: pytest.fail("unexpected HTTP"))
    client = adapter()
    assert client.is_configured() is False
    with pytest.raises(ValueError, match="VISION_MODEL|视觉.*配置"):
        client.process_local_file(image_file(work))


@pytest.mark.parametrize("content", ["", "not JSON", '{"text": ""}', '{"text": {"amount": 35}}'])
def test_empty_or_malformed_vision_response_is_not_success(work, configured, monkeypatch, content):
    monkeypatch.setattr(integrations.requests, "post", lambda *a, **kw: Response(content))
    with pytest.raises((ValueError, RuntimeError), match="视觉|JSON|文本"):
        adapter().process_local_file(image_file(work))


def test_vision_timeout_is_explicit_without_echoing_request(work, configured, monkeypatch, caplog):
    def post(*args, **kwargs):
        raise requests.exceptions.Timeout("vision-test-secret request body should never be logged")
    monkeypatch.setattr(integrations.requests, "post", post)
    with pytest.raises(TimeoutError, match="视觉.*超时") as exc:
        adapter().process_local_file(image_file(work))
    assert "vision-test-secret" not in str(exc.value) + caplog.text


def test_truncated_vision_response_cannot_be_treated_as_complete(work, configured, monkeypatch):
    monkeypatch.setattr(integrations.requests, "post", lambda *a, **kw: Response(
        '{"text":"HANDLING USD 35"}', finish_reason="length"))
    with pytest.raises((ValueError, RuntimeError), match="截断|完整"):
        adapter().process_local_file(image_file(work))


def test_vision_image_has_one_source_and_persisted_raw_without_oss(work):
    vision = FakeVision()
    parsed = parser(work, vision).parse_file(image_file(work))
    assert len(vision.calls) == 1
    assert parsed["content"] == "HANDLING USD 35.00"
    assert len(parsed["blocks"]) == 1
    assert parsed["metadata"]["ocr_provider"] == "vision"
    saved = json.loads(Path(parsed["metadata"]["observation_path"]).read_text(encoding="utf-8"))
    assert saved["metadata"]["ocr_raw"] == vision.results[0]["raw"]
    assert saved["metadata"]["ocr_model"] == "test-vision"
    assert parsed["errors"] == []


def test_mixed_pdf_only_renders_scanned_page_and_cleans_temp(work):
    vision = FakeVision()
    parsed = parser(work, vision).parse_file(make_pdf(work, "VISIBLE FIRST PAGE HANDLING USD 65"))
    assert len(vision.calls) == 1
    assert vision.calls[0].suffix == ".png"
    assert vision.calls[0].is_relative_to(work)
    assert {block["page"] for block in parsed["blocks"]} == {1, 2}
    assert parsed["content"].count("HANDLING USD 35.00") == 1
    assert len(parsed["metadata"]["ocr_raw"]) == 1
    assert parsed["metadata"]["ocr_raw"][0]["page"] == 2
    assert parsed["metadata"]["ocr_raw"][0]["ocr_provider"] == "vision"
    assert not list((work / "ocr-pages").rglob("*"))


def test_missing_renderer_keeps_scanned_page_error_without_calling_vision(work, monkeypatch):
    monkeypatch.setenv("PDFTOPPM_PATH", str(work / "missing-pdftoppm.exe"))
    vision = FakeVision()
    with pytest.raises(ValueError) as exc:
        parser(work, vision).parse_file(make_pdf(work))
    issues = exc.value.metadata["errors"]
    assert issues[0]["page"] == 1
    assert "pdftoppm" in issues[0]["error"].lower() or "poppler" in issues[0]["error"].lower()
    assert not vision.calls
    assert not list((work / "ocr-pages").rglob("*"))


def test_scan_vision_failure_is_explicit_and_removes_local_renders(work):
    with pytest.raises(ValueError) as exc:
        parser(work, FakeVision(error=TimeoutError("timeout"))).parse_file(make_pdf(work))
    assert exc.value.metadata["errors"][0]["code"] == "page_ocr_failed"
    assert not list((work / "ocr-pages").rglob("*"))


def test_eml_keeps_bill_image_and_records_only_confirmed_decoration_as_skipped(work):
    bill = image_file(work)
    logo = image_file(work, "logo.png", "blue")
    message = EmailMessage()
    message.set_content("PRE-ALERT plain body")
    message.add_attachment(bill.read_bytes(), maintype="image", subtype="png", filename="bill.png")
    message.add_attachment(logo.read_bytes(), maintype="image", subtype="png", filename="logo.png")
    path = work / "mail.eml"
    path.write_bytes(message.as_bytes())
    vision = FakeVision([recognition(), recognition("", content_kind="decorative", skip_reason="Only a company logo; no billing information")])
    parsed = parser(work, vision).parse_file(path)
    assert len(vision.calls) == 2
    assert parsed["content"].count("HANDLING USD 35.00") == 1
    assert [a["status"] for a in parsed["attachments"]] == ["success", "skipped"]
    warning = next(e for e in parsed["errors"] if e["code"] == "decorative_content_skipped")
    assert warning["severity"] == "warning" and warning["source_id"] == parsed["attachments"][1]["source_id"]
    assert warning["reason"]
    assert parsed["attachments"][1]["parsed"]["metadata"]["skipped"] is True
    assert Path(parsed["attachments"][1]["parsed"]["metadata"]["observation_path"]).is_file()


@pytest.mark.parametrize("result", [
    recognition("", content_kind="unknown"),
    recognition("", content_kind="decorative"),
    recognition("INVOICE HANDLING USD 300", content_kind="decorative", skip_reason="looks like a logo"),
])
def test_unknown_or_conflicting_image_is_not_silently_skipped(work, result):
    message = EmailMessage()
    message.set_content("PRE-ALERT")
    message.add_attachment(image_file(work).read_bytes(), maintype="image", subtype="png", filename="logo.png")
    path = work / "uncertain.eml"
    path.write_bytes(message.as_bytes())
    parsed = parser(work, FakeVision([result])).parse_file(path)
    assert parsed["attachments"][0]["status"] == "failed"
    assert any(e["code"] == "attachment_parse_failed" for e in parsed["errors"])
    assert not any(e.get("code") == "decorative_content_skipped" for e in parsed["errors"])


def test_failed_vision_transcription_keeps_response_in_failure_observation(work, configured, monkeypatch):
    response = Response('{"text":""}')
    monkeypatch.setattr(integrations.requests, "post", lambda *a, **kw: response)
    with pytest.raises(ValueError) as exc:
        parser(work, adapter()).parse_file(image_file(work))
    metadata = exc.value.metadata
    assert metadata.get("observation_path"), "failed image recognition must leave a traceable observation"
    saved = json.loads(Path(metadata["observation_path"]).read_text(encoding="utf-8"))
    assert saved["metadata"]["ocr_raw"] == response.raw
    assert saved["metadata"]["ocr_provider"] == "vision"
    assert saved["errors"][0]["code"] == "image_ocr_failed"
    assert saved["errors"][0]["severity"] == "error"


def test_decoration_cannot_hide_freight_decimal_amount(work):
    with pytest.raises(ValueError, match="装饰|账单"):
        parser(work, FakeVision([recognition("FREIGHT 300.00", content_kind="decorative", skip_reason="company artwork")])).parse_file(image_file(work))


def test_nested_email_bill_image_uses_vision_once_without_oss(work):
    inner = EmailMessage()
    inner.set_content("INNER PRE-ALERT")
    inner.add_attachment(image_file(work).read_bytes(), maintype="image", subtype="png", filename="bill.png")
    outer = EmailMessage()
    outer.set_content("OUTER PRE-ALERT")
    outer.add_attachment(inner, filename="forwarded.eml")
    path = work / "nested.eml"
    path.write_bytes(outer.as_bytes())
    vision = FakeVision()
    parsed = parser(work, vision).parse_file(path)
    assert len(vision.calls) == 1
    assert parsed["content"].count("HANDLING USD 35.00") == 1
    attached_email = parsed["attachments"][0]["parsed"]
    attached_bill = attached_email["attachments"][0]
    assert attached_bill["parent_source_id"] == attached_email["source_id"]
    assert attached_bill["source_id"] in {b["source_id"] for b in parsed["blocks"]}


def test_vision_rejects_multiframe_image_instead_of_dropping_other_pages(work, configured, monkeypatch):
    path = work / "two-pages.gif"
    Image.new("RGB", (20, 20), "white").save(path, save_all=True,
        append_images=[Image.new("RGB", (20, 20), "blue")], format="GIF")
    monkeypatch.setattr(integrations.requests, "post", lambda *a, **kw: pytest.fail("unexpected HTTP"))
    with pytest.raises(ValueError, match="多帧|单页"):
        adapter().process_local_file(path)


def test_vision_image_limit_blocks_http_before_encoding_large_payload(work, configured, monkeypatch):
    client = adapter()
    monkeypatch.setattr(client, "MAX_IMAGE_BYTES", 8)
    monkeypatch.setattr(integrations.requests, "post", lambda *a, **kw: pytest.fail("unexpected HTTP"))
    with pytest.raises(ValueError, match="限制|超过"):
        client.process_local_file(image_file(work))


def test_invalid_choice_shape_is_reported_and_retained_as_vision_response(work, configured, monkeypatch):
    response = Response("")
    response.raw = {"choices": [None]}
    monkeypatch.setattr(integrations.requests, "post", lambda *a, **kw: response)
    with pytest.raises(ValueError, match="视觉.*文本") as exc:
        adapter().process_local_file(image_file(work))
    assert exc.value.metadata["ocr_raw"] == response.raw


@pytest.mark.parametrize("disposition,cid", [("inline", None), (None, "<bill>")])
def test_unnamed_inline_or_cid_image_is_recognized_as_email_material(work, disposition, cid):
    message = EmailMessage()
    message.set_content('<html><img src="cid:bill"></html>', subtype="html")
    options = {}
    if disposition:
        options["disposition"] = disposition
    if cid:
        options["cid"] = cid
    message.add_related(image_file(work).read_bytes(), maintype="image", subtype="png", **options)
    image = next(part for part in message.walk() if part.get_content_maintype() == "image")
    assert image.get_filename() is None
    path = work / "unnamed-inline.eml"
    path.write_bytes(message.as_bytes())
    vision = FakeVision()
    parsed = parser(work, vision).parse_file(path)
    assert len(vision.calls) == 1
    assert parsed["content"].count("HANDLING USD 35.00") == 1
    assert parsed["attachments"][0]["status"] == "success"
    assert parsed["attachments"][0]["parent_source_id"] == parsed["source_id"]


@pytest.mark.parametrize("text", ["运费 300元", "付款 300元", "收款 300元", "300 元", "运费 300"])
def test_decoration_cannot_hide_chinese_payment_or_integer_yuan_amount(work, text):
    result = recognition(text, content_kind="decorative", skip_reason="company artwork")
    with pytest.raises(ValueError, match="装饰|账单"):
        parser(work, FakeVision([result])).parse_file(image_file(work))
