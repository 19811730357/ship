"""One preview/review/commit pipeline for persistent and in-memory billing."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import re
import uuid
from decimal import Decimal

from .database import CONFIG_VERSION, DatabaseManager, json_text, normalize
from .ledger import load_ledger_from_dict
from .models import AgentDecision, AgentDecisionBatch, Ledger
from .smart_crud import SmartCRUDExecutor
from .validator import validate_document_totals
from .source_amounts import validate_source_totals


class _Overlay:
    """Read-only uploaded baseline; importing it is deferred to explicit commit."""
    def __init__(self, db, entity, records):
        self.db, self.entity = db, entity
        self.records = records

    def query_records_by_document(self, number, entity):
        rows = self.db.query_records_by_document(number, entity)
        rows += [r for r in self.records if normalize(r.document_info.document_number) == normalize(number)]
        return list({r.record_id: r for r in rows}.values())

    def query_records_by_bl(self, value, entity):
        rows = self.db.query_records_by_bl(value, entity)
        rows += [r for r in self.records if normalize(r.document_info.bill_of_lading) == normalize(value)]
        return list({r.record_id: r for r in rows}.values())

    def query_records_by_identifier(self, kind, value, entity):
        rows = self.db.query_records_by_identifier(kind, value, entity)
        for record in self.records:
            doc = record.document_info
            values = {"MBL": [doc.master_bill_of_lading], "HBL": [doc.house_bill_of_lading],
                      "BOOKING": [doc.booking_number], "CONTAINER": doc.container_numbers}.get(kind, [])
            if normalize(value) in {normalize(v) for v in values if v}:
                rows.append(record)
        return list({r.record_id: r for r in rows}.values())


class DatabaseWorkflow:
    def __init__(self, accounting_entity, use_mock_data=True, db_type="sqlite", db_config=None,
                 db_manager=None, agent=None, parser=None, default_posting_type=None,
                 allow_unmapped_charges=None):
        if not str(accounting_entity).strip():
            raise ValueError("记账主体不能为空")
        self.accounting_entity = accounting_entity
        self.use_mock_data = use_mock_data
        self.default_posting_type = (os.getenv("DEFAULT_POSTING_TYPE", "AR") if default_posting_type is None
                                     else default_posting_type).strip().upper() or None
        if self.default_posting_type not in (None, "AR", "AP"):
            raise ValueError("DEFAULT_POSTING_TYPE只能为AR、AP或空值")
        self.allow_unmapped_charges = (os.getenv("ALLOW_UNMAPPED_CHARGES", "true").lower() in ("true", "1", "yes")
                                       if allow_unmapped_charges is None else allow_unmapped_charges)
        self.db = db_manager or DatabaseManager(db_type, db_config)
        self.agent, self.parser = agent, parser
        self._previews = {}

    def _initialize_services(self):
        if self.parser is None:
            from .parsers import DocumentParser
            from .integrations import OCRAdapter, OSSAdapter, VisionOCRAdapter
            backend = os.getenv("OCR_BACKEND", "remote").strip().lower()
            if backend == "vision":
                vision = VisionOCRAdapter()
                # Keep routing enabled so missing configuration names are reported by the adapter.
                self.parser = DocumentParser(ocr_enabled=True, ocr_backend="vision", vision_adapter=vision)
            elif backend == "remote":
                ocr, oss = OCRAdapter(), OSSAdapter()
                self.parser = DocumentParser(ocr_enabled=ocr.is_configured(), ocr_backend="remote",
                                             ocr_adapter=ocr, oss_adapter=oss)
            else:
                raise ValueError("OCR_BACKEND只能为vision或remote")
        if self.agent is None:
            from .agent import BillingAgent
            self.agent = BillingAgent(self.accounting_entity, use_mock=self.use_mock_data,
                                      allow_unmapped_charges=self.allow_unmapped_charges)

    @staticmethod
    def _source_views(parsed):
        names, metadata, source_types = {}, {}, {}
        def visit(item):
            if item.get("metadata", {}).get("skipped"):
                return
            names[item.get("source_id")] = item.get("source_file")
            metadata[item.get("source_id")] = item.get("metadata", {})
            source_types[item.get("source_id")] = item.get("source_type")
            for attachment in item.get("attachments", []):
                if attachment.get("parsed"):
                    visit(attachment["parsed"])
        visit(parsed)
        grouped = {}
        for block in parsed.get("blocks", []):
            sid = block.get("source_id", parsed["source_id"])
            if sid not in names:
                continue
            grouped.setdefault(sid, []).append(block)
        if not grouped and not parsed.get("metadata", {}).get("skipped"):
            grouped[parsed["source_id"]] = [{"source_id": parsed["source_id"], "block_id": "content",
                                             "text": parsed.get("content", "")}]
        return [{"source_id": sid, "source_file": names.get(sid, parsed["source_file"]),
                 "source_type": source_types.get(sid, parsed.get("source_type")), "blocks": blocks,
                 "content": "\n".join(b["text"] for b in blocks),
                 "metadata": metadata.get(sid, {})}
                for sid, blocks in grouped.items()]

    @staticmethod
    def _observation_paths(parsed):
        """Keep all parse observations even when a source is excluded from model input."""
        paths = []
        def visit(item):
            metadata = item.get("metadata", {})
            path = metadata.get("observation_path") or item.get("observation_path")
            if path and path not in paths:
                paths.append(path)
            for attachment in item.get("attachments", []):
                visit(attachment.get("parsed") or attachment)
        visit(parsed)
        return paths

    @staticmethod
    def _combine_parsed_content(sources):
        parts = []
        for source in sources:
            parts.append(f"FILE {source['source_file']} SOURCE_ID {source['source_id']}")
            for block in source.get("blocks", []):
                position = {k: block[k] for k in ("page", "row", "column", "location") if k in block}
                parts.append(f"[source_id={source['source_id']} block_id={block['block_id']} position={json_text(position)}] {block['text']}")
        return "\n".join(parts)

    @staticmethod
    def _signature(allow_updates=False, approved_dictionary=None, policy=None):
        return hashlib.sha256(json_text({"version": CONFIG_VERSION,
            "model": os.getenv("QWEN_MODEL", "qwen-max"), "base": os.getenv("QWEN_BASE_URL", ""),
            "ocr": os.getenv("OCR_URL", ""), "allow_updates": bool(allow_updates),
            "ocr_backend": os.getenv("OCR_BACKEND", "remote"), "vision_model": os.getenv("VISION_MODEL", ""),
            "vision_base": os.getenv("VISION_BASE_URL") or os.getenv("QWEN_BASE_URL", ""),
            "policy": policy,
            "approved_dictionary": approved_dictionary}).encode()).hexdigest()

    def process_real_files(self, file_paths, ledger_data=None, output_dir=None, force_reprocess=False,
                           preview_only=True, allow_updates=False):
        self._initialize_services()
        sources, events, errors, skipped = [], [], [], []
        signature = self._signature(allow_updates, getattr(self.agent, "approved_charge_dictionary", None),
                                    {"default_posting_type": self.default_posting_type,
                                     "allow_unmapped_charges": self.allow_unmapped_charges})
        seen = set()
        for raw_path in file_paths:
            path = Path(raw_path)
            try:
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                if digest in seen:
                    skipped.append(str(path))
                    continue
                seen.add(digest)
                if not force_reprocess and self.db.check_document_processed(
                        raw, self.accounting_entity, processing_signature=signature):
                    skipped.append(str(path))
                    continue
                event = {"document_hash": digest, "file_name": path.name, "status": "pending_review",
                         "results": {"processing_signature": signature}}
                events.append(event)
                parsed = self.parser.parse_file(path)
                event["results"]["observation_paths"] = self._observation_paths(parsed)
                sources.extend(self._source_views(parsed))
                errors.extend({**issue, "origin": "parser", "reviewable": True}
                              for issue in parsed.get("errors", []))
                event["source_ids"] = [s["source_id"] for s in self._source_views(parsed)]
            except Exception as exc:
                errors.append({"file": path.name, "error": str(exc), "origin": "parser", "reviewable": True,
                               "code": "SOURCE_PROCESSING_FAILED", "category": "processing", "severity": "error",
                               "metadata": getattr(exc, "metadata", {})})
                if events and events[-1]["file_name"] == path.name:
                    events[-1]["status"] = "failed"
        if sources:
            empty = Ledger(accounting_entity=self.accounting_entity)
            try:
                batch = self.agent.process_material(self._combine_parsed_content(sources), empty)
                if not isinstance(batch, AgentDecisionBatch):
                    batch = AgentDecisionBatch.model_validate(batch)
            except Exception as exc:
                batch = AgentDecisionBatch(extraction_errors=[{"error": str(exc), "section": "model"}])
        else:
            batch = AgentDecisionBatch()
        result = self.prepare_batch(batch, sources, events=events, errors=errors, ledger_data=ledger_data,
                                    allow_updates=allow_updates, output_dir=output_dir,
                                    files_processed=len(file_paths), files_skipped=len(skipped))
        if not preview_only:
            return self.commit_preview(result["preview_id"])
        return result

    def prepare_batch(self, batch, source_documents, *, events=None, errors=None, ledger_data=None,
                      allow_updates=False, output_dir=None, files_processed=0, files_skipped=0):
        baseline = []
        if ledger_data:
            ledger_data = deepcopy(ledger_data)
            raw_records = ledger_data if isinstance(ledger_data, list) else ledger_data.get("records", [])
            for raw_record in raw_records:
                raw_record.setdefault("record_kind", "legacy_summary")
            uploaded = load_ledger_from_dict(ledger_data, self.accounting_entity)
            for r in uploaded.records:
                if r.financial_attributes.accounting_entity != self.accounting_entity:
                    raise ValueError("导入记录记账主体不一致")
                current = self.db.get_record(r.record_id, self.accounting_entity)
                if current:
                    old_data, incoming_data = current.model_dump(mode="json"), r.model_dump(mode="json")
                    old_data.pop("doc_id", None)
                    incoming_data.pop("doc_id", None)
                    if old_data != incoming_data:
                        raise ValueError("上传旧账与数据库同ID记录不一致，请先核对来源版本")
                if not current:
                    baseline.append(r)
        repository = _Overlay(self.db, self.accounting_entity, baseline)
        dictionary = getattr(self.agent, "approved_charge_dictionary", None)
        planner = SmartCRUDExecutor(repository, self.accounting_entity, dictionary,
                                    default_posting_type=self.default_posting_type,
                                    allow_unmapped_charges=self.allow_unmapped_charges)
        if self.agent and hasattr(self.agent, "repair_missing_identity"):
            batch = self.agent.repair_missing_identity(batch, source_documents)
        if allow_updates and self.agent and hasattr(self.agent, "propose_changes"):
            candidates = {r.record_id: r for d in batch.decisions for r in planner.candidates_for(d)}
            if candidates:
                try:
                    batch = self.agent.propose_changes(batch, Ledger(accounting_entity=self.accounting_entity,
                                                                    records=list(candidates.values())))
                except Exception as exc:
                    batch = batch.model_copy(deep=True)
                    batch.extraction_errors.append({"section": "proposals", "error": str(exc)})
        blocking = deepcopy(list(errors or [])) + [self._model_issue(error) for error in batch.extraction_errors]
        if not batch.decisions and not batch.excluded_items and source_documents:
            blocking.append({"error": "没有识别到费用或明确排除项，不能认定处理成功"})
        plans = [planner.plan(d, source_documents, allow_updates=allow_updates) for d in batch.decisions]
        blocking = self._resolve_issues(blocking, plans)
        decisions = [AgentDecision.model_validate(p["decision"]) for p in plans]
        totals = self._validate_batch(decisions, source_documents)
        self._block_plans(plans, blocking, totals)
        preview_id = str(uuid.uuid4())
        snapshot_versions = {r.record_id: r.version for d in batch.decisions for r in planner.candidates_for(d)}
        if output_dir and Path(output_dir).resolve().drive.upper() != "D:":
            raise ValueError("输出目录必须位于 D 盘")
        state = {"batch": batch.model_copy(deep=True), "sources": deepcopy(source_documents),
                 "events": deepcopy(events or []), "errors": deepcopy(blocking), "totals": totals,
                 "plans": plans, "baseline": baseline, "allow_updates": allow_updates,
                 "output_dir": Path(output_dir) if output_dir else None, "files_processed": files_processed,
                 "files_skipped": files_skipped, "versions": snapshot_versions, "committed_items": set(),
                 "source_reviews": {}, "approved_dictionary": deepcopy(dictionary),
                 "default_posting_type": self.default_posting_type,
                 "allow_unmapped_charges": self.allow_unmapped_charges}
        for index, plan in enumerate(plans):
            plan["item_id"] = str(index)
        self._previews[preview_id] = state
        return self._result(preview_id, state, preview=True, committed=False)

    @staticmethod
    def _validate_batch(decisions, source_documents=None):
        issues = validate_document_totals(decisions) + validate_source_totals(decisions, source_documents or [])
        def anchors(decision):
            result = set()
            for evidence in decision.evidence:
                tokens = re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", evidence.original_text)
                has_amount = any(Decimal(token.replace(",", "")) == decision.charge_details.amount for token in tokens)
                if (evidence.field_name in ("amount", "line_amount", "charge_details.amount")
                    or (not evidence.field_name and has_amount)):
                    result.add((evidence.source_id or evidence.source_file,
                                evidence.block_id or evidence.location or evidence.original_text))
            return result
        for index, first in enumerate(decisions):
            for second in decisions[:index]:
                if (first.document_info.document_number != second.document_info.document_number
                    or normalize(first.transaction_party.issuer) != normalize(second.transaction_party.issuer)
                    or normalize(first.charge_details.original_name) != normalize(second.charge_details.original_name)):
                    continue
                if anchors(first) & anchors(second):
                    issues.append("同一来源费用行被重复提取，需先核对费用完整性")
                first_sources = {e.source_id or e.source_file for e in first.evidence}
                second_sources = {e.source_id or e.source_file for e in second.evidence}
                distinct_refs = (first.charge_details.line_reference and second.charge_details.line_reference
                                 and first.charge_details.line_reference != second.charge_details.line_reference)
                if first_sources != second_sources and not distinct_refs:
                    issues.append("不同来源重复提到同一单据费用，需核对是否重复或修订")
        return list(dict.fromkeys(issues))

    @staticmethod
    def _block_plans(plans, errors, totals):
        issues = [DatabaseWorkflow._issue_message(e) for e in errors if DatabaseWorkflow._is_blocking(e)] + totals
        if issues:
            for plan in plans:
                plan["operation"] = "PENDING_REVIEW"
                plan["validation_issues"] = list(dict.fromkeys(plan["validation_issues"] + issues))
                plan["reason"] = "；".join(plan["validation_issues"])

    @staticmethod
    def _issue_message(issue):
        if not isinstance(issue, dict):
            return str(issue)
        return str(issue.get("error") or issue.get("message") or issue.get("description") or issue.get("code") or "未知处理问题")

    @staticmethod
    def _is_blocking(issue):
        return not isinstance(issue, dict) or not (
            issue.get("severity") in ("warning", "info") or issue.get("blocking") is False
            or issue.get("status") in ("resolved", "resolved_by_policy", "resolved_by_reextraction")
            or issue.get("acknowledged"))

    def _model_issue(self, error):
        issue = deepcopy(error) if isinstance(error, dict) else {"error": str(error)}
        # A model cannot declare an extraction failure resolved or reviewable by itself.
        issue.update(origin="model", reviewable=False, status="open", blocking=True)
        safe_warnings = {"CHARGE_MAPPING_UNKNOWN", "EXCLUDED_TYPE_UNKNOWN", "IDENTITY_REPAIR_FAILED"}
        if issue.get("severity") == "warning" and issue.get("code") in safe_warnings:
            if issue.get("code") != "CHARGE_MAPPING_UNKNOWN" or self.allow_unmapped_charges:
                issue["blocking"] = False
            else:
                issue["severity"] = "error"
        else:
            issue["severity"] = "error"
        return issue

    def _resolve_issues(self, issues, plans):
        result = deepcopy(issues)
        for issue in result:
            if not isinstance(issue, dict) or issue.get("origin") != "model":
                continue
            index = issue.get("item_index")
            affected = [plans[index]] if type(index) is int and 0 <= index < len(plans) else plans
            if not affected:
                continue
            decisions = [AgentDecision.model_validate(p["decision"]) for p in affected]
            code = issue.get("code")
            resolved = code == "POSTING_TYPE_MISSING" and all(d.financial_attributes.posting_type in ("AR", "AP") for d in decisions)
            resolved |= code == "DOCUMENT_IDENTITY_MISSING" and all(
                d.document_info.document_number and d.document_info.document_type and d.transaction_party.issuer for d in decisions)
            if resolved:
                issue.update(status="resolved_by_policy" if code == "POSTING_TYPE_MISSING" else "resolved_by_reextraction", blocking=False)
            elif code == "CHARGE_MAPPING_UNKNOWN" and self.allow_unmapped_charges:
                issue.update(severity="warning", blocking=False)
        return result

    def commit_preview(self, preview_id, review_actions=None):
        if preview_id not in self._previews:
            raise ValueError("预览已失效，请重新解析材料")
        state = self._previews[preview_id]
        actions = deepcopy(review_actions or {})
        source_reviews = actions.pop("__source_reviews__", [])
        for review in source_reviews:
            index = review.get("issue_index")
            if (type(index) is not int or not 0 <= index < len(state["errors"])
                or not state["errors"][index].get("reviewable")
                or state["errors"][index].get("origin") != "parser"
                or not review.get("exclude") or not str(review.get("note", "")).strip()):
                raise ValueError("来源问题仅能在填写依据并确认无关后排除")
            state["source_reviews"][index] = review
        known_ids = {p["item_id"] for p in state["plans"]}
        if set(actions) - known_ids:
            raise ValueError("复核项不属于本次预览")
        # Human selection cannot silently approve a record that changed since preview.
        for record_id, version in state["versions"].items():
            current = self.db.get_record(record_id, self.accounting_entity)
            if not current or current.version != version:
                raise ValueError("候选记录版本已变化，请重新预览")
        planner = SmartCRUDExecutor(_Overlay(self.db, self.accounting_entity, state["baseline"]),
                                    self.accounting_entity, state["approved_dictionary"],
                                    default_posting_type=state["default_posting_type"],
                                    allow_unmapped_charges=state["allow_unmapped_charges"])
        plans = deepcopy(state["plans"])
        decisions = [AgentDecision.model_validate(p["decision"]) for p in plans]
        for index, old_plan in enumerate(plans):
            item_id = old_plan["item_id"]
            if item_id in state["committed_items"]:
                old_plan["operation"] = "NO_CHANGE"
                old_plan["reason"] = "该预览项已提交，本次不重复执行"
                continue
            replacement = planner.plan(decisions[index], state["sources"], allow_updates=state["allow_updates"],
                                       review=actions.get(item_id) or old_plan.get("review"))
            replacement["item_id"] = item_id
            replacement["review"]["source_reviews"] = list(state["source_reviews"].values())
            plans[index] = replacement
            decisions[index] = AgentDecision.model_validate(replacement["decision"])
        totals = self._validate_batch(decisions, state["sources"])
        state["errors"] = self._resolve_issues(state["errors"], plans)
        active_errors = [e for i, e in enumerate(state["errors"]) if i not in state["source_reviews"] and self._is_blocking(e)]
        self._block_plans([p for p in plans if p["item_id"] not in state["committed_items"]], active_errors, totals)
        executable = [p for p in plans if p["operation"] != "PENDING_REVIEW" and p["item_id"] not in state["committed_items"]]
        # Whole-document issues block all associated changes; pending fee identities may be resolved independently.
        pending = any(p["operation"] == "PENDING_REVIEW" for p in plans)
        events = deepcopy(state["events"])
        for event in events:
            if event["status"] != "failed":
                event["status"] = "pending_review" if pending or active_errors else ("committed" if plans else "no_charges")
            event["results"]["preview_id"] = preview_id
            event["results"]["reviewed_source_issues"] = list(state["source_reviews"].values())
            event["results"]["record_versions"] = {
                p["record_id"]: p["after"]["version"] for p in plans if p.get("after") and p["operation"] != "PENDING_REVIEW"}
        if executable or events or state["baseline"]:
            self.db.commit_plans(executable, events, preview_id, self.accounting_entity,
                                 baseline_records=state["baseline"])
        state["baseline"] = []
        state["committed_items"].update(p["item_id"] for p in executable)
        for plan in executable:
            if plan.get("after"):
                state["versions"][plan["record_id"]] = plan["after"]["version"]
        state["plans"] = plans
        state["totals"] = totals
        result = self._result(preview_id, state, preview=False, committed=bool(executable))
        try:
            self._write_outputs(result, state["output_dir"])
        except OSError as exc:
            result["run_report"]["export_error"] = f"账本提交状态已保留，导出失败可重试：{exc}"
        return result

    def _result(self, preview_id, state, *, preview, committed):
        rows = []
        counts = dict.fromkeys(("CREATE", "UPDATE", "NO_CHANGE", "PENDING_REVIEW"), 0)
        for plan in state["plans"]:
            decision = plan["decision"]
            counts[plan["operation"]] += 1
            rows.append({**{k: v for k, v in plan.items() if k not in ("decision",)},
                         "charge_details": decision["charge_details"], "document_info": decision["document_info"],
                         "transaction_party": decision["transaction_party"],
                         "financial_attributes": decision["financial_attributes"]})
        ledger = self.db.load_ledger(self.accounting_entity)
        reported_errors = deepcopy(state["errors"])
        for index, review in state["source_reviews"].items():
            reported_errors[index].update(acknowledged=True, review_note=review["note"])
        active_errors = [issue for issue in reported_errors if self._is_blocking(issue)]
        processing_failed = (not rows and bool(active_errors)) or any(
            isinstance(issue, dict) and (issue.get("origin") == "parser" or issue.get("section") == "model"
                                        or issue.get("category") in {"processing", "system", "configuration", "recognition", "format"})
            for issue in active_errors)
        processing_status = ("PROCESSING_FAILED" if processing_failed else "PENDING_REVIEW"
                             if counts["PENDING_REVIEW"] else "COMMITTED" if committed else "PREVIEW_READY")
        return {"preview_id": preview_id, "preview_only": preview, "committed": committed,
                "session_id": preview_id, "processing_results": rows,
                "source_documents": deepcopy(state["sources"]),
                "ledger_snapshot": ledger.model_dump(mode="json"),
                "database_stats": self.db.get_processing_statistics(self.accounting_entity),
                "summary": {"total_decisions": len(rows), "operations": counts,
                            "excluded_items": len(state["batch"].excluded_items)},
                "run_report": {"files_processed": state["files_processed"],
                               "files_succeeded": len(state["events"]) - sum(e["status"] == "failed" for e in state["events"]),
                               "files_failed": sum(e["status"] == "failed" for e in state["events"]),
                               "files_skipped": state["files_skipped"], "file_errors": reported_errors,
                               "reviewed_source_issues": list(state["source_reviews"].values()),
                               "document_issues": state["totals"], "preview_only": preview,
                               "excluded_items": [e.model_dump(mode="json") for e in state["batch"].excluded_items],
                               "processing_status": processing_status,
                               "using_mock_data": self.use_mock_data, "database_enabled": self.db.db_config.get("database") != ":memory:"}}

    @staticmethod
    def _write_outputs(result, output_dir):
        if output_dir:
            directory = Path(output_dir).resolve()
            if directory.drive.upper() != "D:":
                raise ValueError("输出目录必须位于 D 盘")
            directory.mkdir(parents=True, exist_ok=True)
            for name in ("processing_results", "ledger_snapshot", "run_report"):
                target = directory / f"{name}.json"
                temporary = target.with_suffix(".json.tmp")
                temporary.write_text(json_text(result[name]), encoding="utf-8")
                temporary.replace(target)

    def get_ledger_from_database(self):
        return self.db.load_ledger(self.accounting_entity)

    def query_by_document(self, number):
        return self.db.query_records_by_document(number, self.accounting_entity)

    def query_by_bl(self, number):
        return self.db.query_records_by_bl(number, self.accounting_entity)

    def get_statistics(self):
        return self.db.get_processing_statistics(self.accounting_entity)

    def close(self):
        self.db.close()
