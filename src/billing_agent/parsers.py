"""Parse documents into attributable text blocks, including email children."""
from .runtime import configure_runtime, SOURCE_DIR, ROOT_DIR
configure_runtime()

import hashlib
import base64
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path, PureWindowsPath

import PyPDF2
import pandas as pd
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from PIL import Image


class OCRProcessingError(ValueError):
    def __init__(self, message, metadata=None):
        super().__init__(message)
        self.metadata = metadata or {}


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("br", "p", "div", "tr", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag in ("p", "div", "tr", "li"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _safe_name(name):
    """Use an ASCII cloud filename; keep the original name in source metadata."""
    suffix = PureWindowsPath(str(name).replace("/", "\\")).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        suffix = ".bin"
    # The caller's UUID directory provides uniqueness. Percent-encoded original
    # names can download correctly yet produce an empty company OCR response.
    return f"document{suffix}"


def _attachment_parts(message):
    """Include inline assets without traversing an attached message twice."""
    for part in message.iter_parts() if message.is_multipart() else ():
        if (part.get_content_type() == "message/rfc822" or part.get_filename()
                or part.get_content_disposition() == "attachment"
                or (part.get_content_maintype() == "image" and
                    (part.get_content_disposition() == "inline" or part.get("Content-ID")))):
            yield part
        elif part.is_multipart():
            yield from _attachment_parts(part)


class DocumentParser:
    MAX_FILE_BYTES = 64 * 1024 * 1024
    MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
    MAX_EMAIL_BYTES = 100 * 1024 * 1024
    MAX_DEPTH = 4

    def __init__(self, ocr_enabled=False, ocr_adapter=None, oss_adapter=None, work_dir=None,
                 ocr_backend=None, vision_adapter=None, non_billing_assets=None):
        self.ocr_enabled, self.ocr_adapter, self.oss_adapter = ocr_enabled, ocr_adapter, oss_adapter
        # Explicit legacy adapters retain their URL/OSS protocol unless a backend is selected.
        self.ocr_backend = ocr_backend or ("vision" if vision_adapter is not None else "remote")
        if self.ocr_backend not in ("vision", "remote"):
            raise ValueError("OCR_BACKEND 仅支持 vision 或 remote")
        self.vision_adapter = vision_adapter
        if non_billing_assets is None:
            catalog = ROOT_DIR / "config" / "non_billing_assets.json"
            non_billing_assets = json.loads(catalog.read_text(encoding="utf-8")) if catalog.is_file() else {}
        if not isinstance(non_billing_assets, dict):
            raise ValueError("已核验的非账单素材清单必须为摘要到核验记录的对象")
        self.non_billing_assets = {digest: review for digest, review in non_billing_assets.items()
            if re.fullmatch(r"[a-f0-9]{64}", str(digest)) and isinstance(review, dict)
            and review.get("approved") is True and review.get("scope") == "email_attachment"
            and isinstance(review.get("reason"), str) and review["reason"].strip()
            and isinstance(review.get("reviewed_by"), str) and review["reviewed_by"].strip()}
        self.work_dir = Path(work_dir).resolve() if work_dir else SOURCE_DIR
        if self.work_dir.drive and self.work_dir.drive.upper() != "D:":
            raise ValueError("解析缓存和来源档案必须位于 D 盘")
        if os.name == "nt" and len(str(self.work_dir)) > 150:
            raise ValueError("解析工作目录路径过长，请选择较短的 D 盘目录")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._depth, self._email_bytes = 0, 0
        self._original_names = {}

    def _display_name(self, path):
        return self._original_names.get(str(Path(path).resolve()), Path(path).name)

    def _archive_path(self, source_id, name):
        # The digest preserves identity; raw names stay in metadata instead of
        # making nested archives exceed the Windows MAX_PATH limit.
        suffix = PureWindowsPath(str(name)).suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
            suffix = ".bin"
        return self.work_dir / "archive" / source_id[:2] / f"{source_id}{suffix}"

    def _archive(self, path):
        path = Path(path)
        if path.stat().st_size > self.MAX_FILE_BYTES:
            raise ValueError("文件超过 64 MiB 解析限制")
        raw = path.read_bytes()
        source_id = hashlib.sha256(raw).hexdigest()
        archive = self._archive_path(source_id, self._display_name(path))
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            archive.write_bytes(raw)
        return source_id, archive

    def _blocks(self, source_id, text, *, page=None, prefix="text", **extra):
        blocks = []
        for row, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            block = {"source_id": source_id, "block_id": f"{source_id}:{prefix}:r{row}",
                     "text": line, "row": row, "location": f"{prefix}, line {row}", **extra}
            if page is not None:
                block["page"] = page
            blocks.append(block)
        return blocks

    def _result(self, path, source_type, blocks, metadata=None, attachments=None, errors=None, empty_error=None):
        source_id, archive = self._archive(path)
        result = {"content": "\n".join(block["text"] for block in blocks),
                  "source_id": source_id, "source_file": self._display_name(path),
                  "source_type": source_type, "blocks": blocks,
                  "metadata": {"archive_path": str(archive), "original_filename": self._display_name(path),
                               **(metadata or {})},
                  "attachments": attachments or [], "errors": errors or []}
        self._save_observation(result)
        if (not blocks or not any(block["text"].strip() for block in blocks)) and not result["metadata"].get("skipped"):
            raise OCRProcessingError(empty_error or "没有取得可识别文本；文件未被标记为解析成功",
                                     {"source_id": source_id, **result["metadata"], "errors": errors or []})
        return result

    def _save_observation(self, result):
        """Persist one immutable parse observation without repeating child payloads."""
        source_hash = result["source_id"].removeprefix("url-")
        folder = self.work_dir / "observations" / source_hash[:2]
        folder.mkdir(parents=True, exist_ok=True)
        # URL-safe base64 retains all 128 UUID bits in 22 characters, keeping the
        # full source hash and the complete Windows path below MAX_PATH.
        nonce = base64.urlsafe_b64encode(uuid.uuid4().bytes).decode("ascii").rstrip("=")
        target = folder / f"{source_hash}-{nonce}.json"
        if os.name == "nt" and len(str(target)) >= 260:
            raise ValueError("来源观察记录路径过长，请选择较短的 D 盘解析目录")
        result["metadata"]["observation_path"] = str(target)
        references = []
        for attachment in result.get("attachments", []):
            reference = {key: value for key, value in attachment.items() if key != "parsed"}
            child = attachment.get("parsed")
            if child:
                reference["observation_path"] = child.get("metadata", {}).get("observation_path")
            references.append(reference)
        payload = {**result, "attachments": references}
        with target.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)

    def parse_file(self, file_path):
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"文件不存在: {path}")
        if path.stat().st_size > self.MAX_FILE_BYTES:
            raise ValueError("文件超过 64 MiB 解析限制")
        with path.open("rb") as stream:
            signature = stream.read(16)
        suffix = path.suffix.lower()
        if signature.startswith(b"%PDF"):
            return self.parse_pdf(path)
        if signature.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"II*\x00", b"MM\x00*")):
            return self.parse_image(path)
        dispatch = {".eml": self.parse_eml, ".pdf": self.parse_pdf,
                    ".xlsx": self.parse_excel, ".xls": self.parse_excel, ".csv": self.parse_excel,
                    ".docx": self.parse_word, ".txt": self.parse_txt,
                    ".png": self.parse_image, ".jpg": self.parse_image, ".jpeg": self.parse_image,
                    ".bmp": self.parse_image, ".tif": self.parse_image, ".tiff": self.parse_image,
                    ".gif": self.parse_image}
        if suffix not in dispatch:
            raise ValueError(f"不支持的文件格式: {suffix or 'unknown'}")
        return dispatch[suffix](path)

    def parse_eml(self, file_path):
        path = Path(file_path)
        source_id, _ = self._archive(path)
        if self._depth >= self.MAX_DEPTH:
            raise ValueError("邮件附件嵌套超过允许深度")
        if self._depth == 0:
            self._email_bytes = 0
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        body = message.get_body(preferencelist=("plain", "html"))
        text = ""
        if body:
            text = body.get_content()
            if body.get_content_type() == "text/html":
                parser = _HTMLText()
                parser.feed(text)
                text = "".join(parser.parts)
        blocks = []
        for name in ("Subject", "From", "To", "Date"):
            value = str(message.get(name, ""))
            if value:
                blocks.append({"source_id": source_id,
                               "block_id": f"{source_id}:email-header:{name.lower()}",
                               "text": f"{name}: {value}", "location": f"email header {name}",
                               "field_name": f"email.{name.lower()}"})
        blocks.extend(self._blocks(source_id, text, prefix="email-body"))
        attachments, errors = [], []
        self._depth += 1
        try:
            for index, part in enumerate(_attachment_parts(message), 1):
                # 避免使用 mimetypes.guess_extension（编码问题）
                content_type = part.get_content_type()
                ext_map = {
                    'image/jpeg': '.jpg',
                    'image/png': '.png',
                    'image/gif': '.gif',
                    'application/pdf': '.pdf',
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
                    'application/vnd.ms-excel': '.xls',
                    'text/plain': '.txt',
                    'text/html': '.html',
                }
                ext = ext_map.get(content_type, '.bin')
                filename = part.get_filename() or f"attachment-{index}{ext}"
                if part.get_content_type() == "message/rfc822":
                    payload = part.get_payload()
                    raw = payload[0].as_bytes() if isinstance(payload, list) and payload else b""
                    if not Path(filename).suffix:
                        filename += ".eml"
                else:
                    raw = part.get_payload(decode=True) or b""
                child_id = hashlib.sha256(raw).hexdigest()
                child_path = self._archive_path(child_id, filename)
                self._original_names[str(child_path.resolve())] = filename
                entry = {"filename": filename, "content_type": part.get_content_type(), "size": len(raw),
                         "source_id": child_id, "parent_source_id": source_id,
                         "archive_path": str(child_path), "status": "failed"}
                attachments.append(entry)
                try:
                    self._email_bytes += len(raw)
                    if len(raw) > self.MAX_ATTACHMENT_BYTES or self._email_bytes > self.MAX_EMAIL_BYTES:
                        raise ValueError("邮件附件超过大小限制")
                    child_path.parent.mkdir(parents=True, exist_ok=True)
                    if not child_path.exists():
                        child_path.write_bytes(raw)
                    review = self.non_billing_assets.get(child_id)
                    if review and part.get_content_maintype() == "image":
                        parsed = self._result(child_path, "image", [], {
                            "skipped": True, "content_kind": "reviewed_non_billing_asset",
                            "skip_reason": review["reason"], "asset_review": review}, errors=[{
                                "code": "reviewed_non_billing_asset", "severity": "warning",
                                "source_id": child_id, "message": "已跳过按文件摘要核验的无关邮件素材",
                                "reason": review["reason"]}])
                    else:
                        parsed = self.parse_file(child_path)
                    status = "skipped" if parsed["metadata"].get("skipped") else (
                        "partial" if any(issue.get("severity") != "warning" for issue in parsed["errors"]) else "success")
                    entry.update(status=status, parsed=parsed)
                    blocks.extend({**block, "parent_source_id": block.get("parent_source_id", source_id)}
                                  for block in parsed["blocks"])
                    errors.extend(parsed["errors"])
                except Exception as exc:
                    error = {"code": "attachment_parse_failed", "source_id": child_id,
                             "parent_source_id": source_id, "filename": filename, "error": str(exc)}
                    if getattr(exc, "metadata", None):
                        error["metadata"] = exc.metadata
                    errors.append(error)
                    entry["error"] = str(exc)
        finally:
            self._depth -= 1
        return self._result(path, "email", blocks, {
            "subject": str(message.get("subject", "")), "from": str(message.get("from", "")),
            "to": str(message.get("to", "")), "date": str(message.get("date", "")),
            "has_attachments": bool(attachments)}, attachments, errors)

    def parse_pdf(self, file_path):
        path = Path(file_path)
        source_id, _ = self._archive(path)
        reader = PyPDF2.PdfReader(io.BytesIO(path.read_bytes()))
        blocks, errors, raw_ocr = [], [], []
        for page_number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if len(text.strip()) >= 20:
                blocks.extend(self._blocks(source_id, text, page=page_number, prefix=f"page-{page_number}"))
                continue
            if not self.ocr_enabled or (self.ocr_backend == "remote" and not self.ocr_adapter):
                errors.append({"code": "page_requires_ocr", "source_id": source_id,
                               "page": page_number, "error": "PDF页面文本不足，需要OCR"})
                if text.strip():
                    blocks.extend(self._blocks(source_id, text, page=page_number, prefix=f"page-{page_number}"))
                continue
            page_path = self.work_dir / "ocr-pages" / f"{uuid.uuid4().hex}.pdf"
            page_path.parent.mkdir(parents=True, exist_ok=True)
            writer = PyPDF2.PdfWriter()
            writer.add_page(page)
            with page_path.open("wb") as stream:
                writer.write(stream)
            try:
                recognized, metadata, page_errors = self._ocr_local(page_path)
                raw_ocr.append({"page": page_number, **metadata})
                errors.extend({**issue, "source_id": source_id, "page": page_number} for issue in page_errors)
                blocks.extend(self._blocks(source_id, recognized, page=page_number, prefix=f"page-{page_number}-ocr"))
            except OCRProcessingError as exc:
                errors.append({"code": "page_ocr_failed", "source_id": source_id,
                               "page": page_number, "error": str(exc), "metadata": exc.metadata})
            finally:
                page_path.unlink(missing_ok=True)
        return self._result(path, "pdf", blocks, {"num_pages": len(reader.pages),
                            "ocr_processed": bool(raw_ocr), "ocr_raw": raw_ocr}, errors=errors)

    def _pending_cleanup(self, object_name, reason):
        path = self.work_dir / "cleanup-pending" / f"{uuid.uuid4().hex}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {"object_name": object_name, "reason": reason, "cleanup_pending": True,
                 "action": "确认OCR服务已停止读取后，仅清理本任务创建的对象"}
        path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
        return {**event, "cleanup_record": str(path)}

    def _ocr_local(self, path):
        if self.ocr_backend == "vision":
            return self._vision_local(path)
        if not self.ocr_enabled or not self.ocr_adapter:
            raise OCRProcessingError("OCR未启用，不能识别此材料")
        if self.oss_adapter is None:
            from .integrations import OSSAdapter
            self.oss_adapter = OSSAdapter()
        if not self.oss_adapter.is_configured():
            raise OCRProcessingError(
                "公司OCR接口的file参数需要可访问的图片/PDF URL；当前本地文件缺少上传或链接获取方式。"
                "这不需要视觉模型，也不能仅凭示例假定支持Base64或文件直传；原文件已保留。",
                {"code": "OCR_FILE_URL_REQUIRED", "ocr_backend": "remote", "required_input": "file_url",
                 "category": "configuration", "needs_vision_model": False,
                 "message": "请由题方确认可访问文件链接或配套上传协议；OSS只是已有的可选URL桥接方式"})
        object_name = f"billing-ocr/{uuid.uuid4().hex}/{_safe_name(Path(path).name)}"
        metadata, errors = {}, []
        try:
            url = self.oss_adapter.upload_file(str(path), object_name)
        except Exception as exc:
            metadata.update(getattr(exc, "metadata", {}))
            if metadata.get("object_created") is not False:
                try:
                    self.oss_adapter.delete_file(object_name)
                except Exception:
                    metadata.update(self._pending_cleanup(object_name, "上传或签名失败，清理未完成"))
            detail = str(exc) if getattr(exc, "metadata", None) else "OCR素材上传失败"
            raise OCRProcessingError(detail, metadata) from None
        try:
            raw = self.ocr_adapter.process_file(url, task="orderChange")
        except Exception:
            metadata.update(self._pending_cleanup(object_name, "OCR请求未获得终态，不能确定服务是否仍在读取"))
            raise OCRProcessingError("OCR请求失败或超时，云端对象保留待核实清理", metadata)
        metadata["ocr_raw"] = raw
        metadata["ocr_content_type"] = "company_structured_fields" if self._is_company_response(raw) else "text"
        if isinstance(raw, dict) and str(raw.get("status", "")).lower() in ("pending", "running", "processing", "queued"):
            metadata.update(self._pending_cleanup(object_name, "OCR任务仍在处理中"))
            raise OCRProcessingError("OCR尚未完成，云端对象保留待清理", metadata)
        try:
            self._validate_ocr_result(raw)
            text = self._extract_ocr_text(raw)
            if not text.strip():
                metadata.update(code="OCR_EMPTY_RESULT", category="recognition")
                if self._is_company_response(raw):
                    raise ValueError("公司OCR返回结果为空，未提供可识别字段或费用；原始响应已保存")
                raise ValueError("OCR未返回可识别文本")
        except Exception as exc:
            try:
                self.oss_adapter.delete_file(object_name)
            except Exception:
                metadata.update(self._pending_cleanup(object_name, "OCR失败后的对象清理失败"))
            raise OCRProcessingError(f"OCR识别失败: {exc}", metadata)
        try:
            self.oss_adapter.delete_file(object_name)
        except Exception:
            metadata.update(self._pending_cleanup(object_name, "OCR已返回结果，但对象清理失败"))
            errors.append({"code": "cleanup_pending", "error": "本次OCR云端对象清理失败", **metadata})
        metadata["ocr_processed"] = True
        return text, metadata, errors

    def _vision_local(self, path):
        if not self.ocr_enabled:
            raise OCRProcessingError("视觉OCR未启用，不能识别此材料")
        if self.vision_adapter is None:
            from .integrations import VisionOCRAdapter
            self.vision_adapter = VisionOCRAdapter()
        if not self.vision_adapter.is_configured():
            raise OCRProcessingError("视觉识别未配置，请设置 VISION_MODEL、服务地址和 API 密钥")
        try:
            if Path(path).suffix.lower() == ".pdf":
                renderer = shutil.which(os.getenv("PDFTOPPM_PATH") or "pdftoppm")
                if not renderer:
                    raise ValueError("扫描PDF需要Poppler pdftoppm，请配置 PDFTOPPM_PATH")
                render_dir = self.work_dir / "ocr-pages"
                render_dir.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(dir=render_dir) as folder:
                    prefix = Path(folder) / "page"
                    command = [renderer, "-f", "1", "-l", "1", "-singlefile", "-scale-to", "2400",
                               "-png", str(path), str(prefix)]
                    subprocess.run(command, check=True, capture_output=True, timeout=60,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    result = self.vision_adapter.process_local_file(prefix.with_suffix(".png"))
            else:
                result = self.vision_adapter.process_local_file(path)
        except Exception as exc:
            if isinstance(exc, (subprocess.CalledProcessError, subprocess.TimeoutExpired)):
                raise OCRProcessingError("Poppler pdftoppm渲染失败或超时") from None
            metadata = {"ocr_backend": "vision", "ocr_provider": "vision", **getattr(exc, "metadata", {})}
            raise OCRProcessingError("视觉识别失败：" + str(exc), metadata) from None
        if not isinstance(result, dict) or not isinstance(result.get("text"), str):
            raise OCRProcessingError("视觉识别未返回有效文本")
        text = result["text"]
        metadata = {"ocr_processed": True, "ocr_backend": "vision",
                    "ocr_provider": result.get("provider", "vision"), "ocr_model": result.get("model"),
                    "ocr_raw": result.get("raw", {}), "content_kind": result.get("content_kind", "unknown")}
        if metadata["content_kind"] == "decorative":
            reason = result.get("skip_reason")
            billing_text = re.search(
                r"\b(?:INVOICE|DEBIT|CREDIT|AMOUNT|TOTAL|CHARGES?|FEES?|RATE|FREIGHT|HANDLING|"
                r"DETENTION|DEMURRAGE|STORAGE|TARIFF|USD|CNY|RMB|EUR|GBP|JPY|CAD|AUD|CHF|HKD|SGD|"
                r"PAYMENT|PAYABLE|DUE|BALANCE)\b|账单|费用|金额|应付|应收|运费|付款|收款|人民币|"
                r"[￥$€]|\d+[.,]\d{2}|\d[\d,]*(?:\.\d+)?\s*[元圆块]", text, re.I)
            if not isinstance(reason, str) or not reason.strip() or billing_text:
                raise OCRProcessingError("装饰图片判定缺少依据或与账单文字冲突", metadata)
            metadata.update(skipped=True, skip_reason=reason.strip())
            warning = {"code": "decorative_content_skipped", "severity": "warning",
                       "error": "已跳过明确无关的装饰素材", "reason": reason.strip()}
            return "", metadata, [warning]
        if not text.strip():
            raise OCRProcessingError("视觉识别未返回可识别文本", metadata)
        return text, metadata, []

    @staticmethod
    def _validate_ocr_result(result):
        if not isinstance(result, dict):
            raise ValueError("OCR响应必须是对象")
        if result.get("success") is False:
            raise ValueError("OCR服务报告处理失败")
        if "code" in result and result["code"] not in (0, 200, "0", "200"):
            raise ValueError("OCR服务返回非成功状态")
        if str(result.get("status", "")).lower() in ("pending", "running", "processing", "queued"):
            raise ValueError("OCR尚未处理完成")

    def _extract_ocr_text(self, result):
        if self._is_company_response(result):
            return self._company_response_text(result["data"]["list"])
        keys = ("text", "markdown", "content", "lines", "blocks", "pages", "data", "result", "results", "words_result", "cells")
        def walk(value):
            if isinstance(value, str):
                return [value] if value.strip() else []
            if isinstance(value, list):
                return [text for entry in value for text in walk(entry)]
            if isinstance(value, dict):
                for key in ("text", "markdown", "content"):
                    if isinstance(value.get(key), str) and value[key].strip():
                        return [value[key]]
                return [text for key in keys if key in value for text in walk(value[key])]
            return []
        return "\n".join(walk(result))

    @staticmethod
    def _is_company_response(result):
        return (isinstance(result, dict) and isinstance(result.get("data"), dict)
                and isinstance(result["data"].get("list"), list))

    @staticmethod
    def _company_response_text(records):
        """Expose observed business fields without calling them verbatim image text."""
        def present(value):
            if isinstance(value, dict):
                return any(present(item) for item in value.values())
            if isinstance(value, list):
                return any(present(item) for item in value)
            return value is not None and value != ""

        def cell(value):
            return json.dumps(value, ensure_ascii=False, default=str).replace("|", "\\u007c")

        lines = []
        administrative = {"chargeList", "page_index", "fileType", "suspicious", "isDetention", "isDemurrage"}
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError("公司OCR data.list条目必须为对象")
            charges = record.get("chargeList") or []
            if not isinstance(charges, list) or any(not isinstance(charge, dict) for charge in charges):
                raise ValueError("公司OCR chargeList必须为费用对象数组")
            facts = [(key, value) for key, value in record.items() if key not in administrative and present(value)]
            actual_charges = [charge for charge in charges if any(present(v) for v in charge.values())]
            if not facts and not actual_charges:
                continue
            lines.append(f"公司OCR结构化观察 data.list[{index}]（接口提取字段，非图片逐字转录）")
            for key, value in facts:
                lines.append(f"data.list[{index}].{key}: {cell(value)}")
            if actual_charges:
                lines.append(f"data.list[{index}].chargeList:")
                lines.append("| chargeItem | amount | currency | chargeCtr |")
                lines.append("| --- | --- | --- | --- |")
                for charge in actual_charges:
                    lines.append("| " + " | ".join(cell(charge.get(key)) for key in
                        ("chargeItem", "amount", "currency", "chargeCtr")) + " |")
        return "\n".join(lines)

    def parse_image(self, file_path):
        path = Path(file_path)
        source_id, _ = self._archive(path)
        with Image.open(path) as image:
            metadata = {"format": image.format, "size": image.size, "mode": image.mode}
            image.verify()
        try:
            text, ocr_metadata, errors = self._ocr_local(path)
        except OCRProcessingError as exc:
            errors = [{"code": "image_ocr_failed", "severity": "error", "source_id": source_id,
                       "error": str(exc), "metadata": exc.metadata}]
            return self._result(path, "image", [], {**metadata, **exc.metadata}, errors=errors,
                                empty_error=str(exc))
        errors = [{**issue, "source_id": source_id} for issue in errors]
        return self._result(path, "image", self._blocks(source_id, text, page=1, prefix="image-ocr"),
                            {**metadata, **ocr_metadata}, errors=errors)

    def parse_file_from_url(self, file_url, file_type="pdf"):
        if not self.ocr_enabled or not self.ocr_adapter:
            raise ValueError("OCR未启用，无法处理URL文件")
        raw = self.ocr_adapter.process_file(file_url, task="orderChange")
        self._validate_ocr_result(raw)
        text = self._extract_ocr_text(raw)
        if not text.strip():
            raise ValueError("OCR未返回可识别文本")
        source_id = "url-" + hashlib.sha256(file_url.encode()).hexdigest()
        result = {"content": text, "source_id": source_id, "source_file": "remote-document",
                  "source_type": file_type, "blocks": self._blocks(source_id, text, prefix="remote-ocr"),
                  "metadata": {"ocr_raw": raw, "ocr_processed": True, "source_identity": "url_observation",
                               "ocr_content_type": "company_structured_fields" if self._is_company_response(raw) else "text"},
                  "attachments": [], "errors": []}
        self._save_observation(result)
        return result

    def parse_txt(self, file_path):
        path = Path(file_path)
        source_id, _ = self._archive(path)
        for encoding in ("utf-8-sig", "utf-16", "gb18030"):
            try:
                text = path.read_text(encoding=encoding)
                break
            except UnicodeError:
                continue
        else:
            raise ValueError("无法解码文本文件")
        return self._result(path, "text", self._blocks(source_id, text), {"size": path.stat().st_size})

    def parse_excel(self, file_path):
        path = Path(file_path)
        source_id, _ = self._archive(path)
        tables = {"Sheet1": pd.read_csv(path, header=None, dtype=str, keep_default_na=False)} if path.suffix.lower() == ".csv" else pd.read_excel(path, sheet_name=None, header=None, dtype=str, keep_default_na=False)
        blocks = []
        for name, table in tables.items():
            for row_index, values in enumerate(table.itertuples(index=False, name=None), 1):
                text = "\t".join(str(value) for value in values)
                if text.strip():
                    blocks.append({"source_id": source_id, "block_id": f"{source_id}:sheet:{name}:r{row_index}",
                                   "text": text, "row": row_index, "sheet": name,
                                   "location": f"{name}!row {row_index}",
                                   "cells": [{"column": column, "value": value} for column, value in enumerate(values, 1)]})
        return self._result(path, "excel", blocks, {"num_sheets": len(tables), "sheet_names": list(tables)})

    def parse_word(self, file_path):
        path = Path(file_path)
        source_id, _ = self._archive(path)
        document = Document(path)
        blocks = []
        for index, child in enumerate(document.element.body.iterchildren(), 1):
            if child.tag.endswith("}p"):
                text = Paragraph(child, document).text
                if text.strip():
                    blocks.extend(self._blocks(source_id, text, prefix=f"paragraph-{index}"))
            elif child.tag.endswith("}tbl"):
                for row_index, row in enumerate(Table(child, document).rows, 1):
                    text = "\t".join(cell.text for cell in row.cells)
                    if text.strip():
                        blocks.append({"source_id": source_id, "block_id": f"{source_id}:table-{index}:r{row_index}",
                                       "text": text, "row": row_index, "location": f"table {index}, row {row_index}"})
        return self._result(path, "word", blocks)
