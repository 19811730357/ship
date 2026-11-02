"""Build explicit change plans. This module never writes while deciding."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import re
import uuid

from .database import normalize
from .models import AuditTrail, Evidence, LedgerRecord
from .validator import CHARGE_NAME_MAPPING, evidence_exists, validate_extracted_charge

PATCH_FIELDS = {
    "charge_details.amount", "charge_details.currency", "charge_details.payment_method",
    "charge_details.standardized_name", "charge_details.quantity", "charge_details.unit_price",
    "charge_details.settlement_amount", "charge_details.settlement_currency",
    "charge_details.exchange_rate",
}


class SmartCRUDExecutor:
    def __init__(self, db, accounting_entity, approved_charge_dictionary=None):
        self.db = db
        self.accounting_entity = accounting_entity
        dictionary = CHARGE_NAME_MAPPING if approved_charge_dictionary is None else approved_charge_dictionary
        self.approved_charge_dictionary = {" ".join(key.lower().split()): value for key, value in dictionary.items()}

    def candidates_for(self, decision):
        doc = decision.document_info
        rows = self.db.query_records_by_document(doc.document_number, self.accounting_entity) if doc.document_number else []
        if not rows:
            references = [("MBL", doc.master_bill_of_lading), ("HBL", doc.house_bill_of_lading),
                          ("BL", doc.bill_of_lading), ("BOOKING", doc.booking_number)]
            references += [("CONTAINER", v) for v in doc.container_numbers]
            rows_by_id = {}
            for kind, value in references:
                if value:
                    candidates = self.db.query_records_by_identifier(kind, value, self.accounting_entity)
                    if kind == "BL":
                        candidates += self.db.query_records_by_bl(value, self.accounting_entity)
                    rows_by_id.update({r.record_id: r for r in candidates})
            rows = list(rows_by_id.values())
        issuer = normalize(decision.transaction_party.issuer)
        # Unknown issuer stays in the candidate set so missing data cannot imply "new".
        rows = [r for r in rows if not issuer or not r.transaction_party.issuer
                or normalize(r.transaction_party.issuer) == issuer]
        return rows

    def plan(self, decision, source_documents=None, allow_updates=False, review=None):
        decision = decision.model_copy(deep=True)
        original_candidates = self.candidates_for(decision)
        sources = source_documents or []
        review = review or {}
        human = bool(review.get("note", "").strip())
        if review and not human:
            return self._pending(decision, [], ["人工复核必须填写依据说明"])
        if human:
            for field in ("amount", "currency", "standardized_name"):
                if review.get(field) is not None:
                    value = review[field]
                    if field == "amount":
                        value = Decimal(str(value))
                    setattr(decision.charge_details, field, value)
            for field, obj in (("issuer", decision.transaction_party), ("document_number", decision.document_info),
                               ("posting_type", decision.financial_attributes)):
                if review.get(field):
                    setattr(obj, field, review[field])
            decision.evidence.append(Evidence(
                source_file="human_review", source_type="human_review",
                original_text=review["note"], field_name="review"))
        if decision.financial_attributes.accounting_entity != self.accounting_entity:
            return self._pending(decision, [], ["记账主体不一致"])
        issues = validate_extracted_charge(decision, sources, human_review=human,
                                          approved_charge_dictionary=self.approved_charge_dictionary)
        rows = self.candidates_for(decision)
        if human:
            rows = list({r.record_id: r for r in original_candidates + rows}.values())
        if decision.suggested_operation == "PENDING_REVIEW" and not human:
            issues.append("模型报告待复核：" + decision.operation_reasoning)
        named = [r for r in rows if
                 normalize(r.charge_details.original_name) == normalize(decision.charge_details.original_name)
                 or (decision.charge_details.standardized_name and
                     r.charge_details.standardized_name == decision.charge_details.standardized_name)]
        matched = None
        selected_id = review.get("record_id")
        if selected_id:
            matched = next((r for r in rows if r.record_id == selected_id), None)
            if not matched:
                issues.append("选择的记录不在当前主体候选范围")
        elif review.get("approve_create") and human:
            # Explicit new-charge approval does not erase validation errors.
            matched = None
        elif len(named) == 1:
            matched = named[0]
        elif len(named) > 1:
            line_ref = decision.charge_details.line_reference
            specific = [r for r in named if line_ref and r.charge_details.line_reference == line_ref]
            if len(specific) == 1:
                matched = specific[0]
            else:
                issues.append("存在多条同名费用，必须提供稳定明细标识或人工选择")
        if matched:
            if not decision.financial_attributes.posting_type:
                decision.financial_attributes.posting_type = matched.financial_attributes.posting_type
                decision.financial_attributes.posting_type_reasoning = matched.financial_attributes.posting_type_reasoning
            if not decision.charge_details.standardized_name:
                decision.charge_details.standardized_name = matched.charge_details.standardized_name
            dictionary = dict(self.approved_charge_dictionary)
            if (normalize(matched.charge_details.original_name) == normalize(decision.charge_details.original_name)
                and matched.charge_details.standardized_name):
                dictionary[" ".join(decision.charge_details.original_name.lower().split())] = matched.charge_details.standardized_name
            issues = validate_extracted_charge(decision, sources, human_review=human,
                                              approved_charge_dictionary=dictionary)
            if decision.suggested_operation == "PENDING_REVIEW" and not human:
                issues.append("模型报告待复核：" + decision.operation_reasoning)
            old_doc, new_doc = matched.document_info, decision.document_info
            if not human:
                if (decision.charge_details.line_reference and matched.charge_details.line_reference
                    and decision.charge_details.line_reference != matched.charge_details.line_reference):
                    issues.append("稳定明细标识不一致，不能认定为同一费用")
                if decision.matched_record_id and decision.matched_record_id != matched.record_id:
                    issues.append("模型候选选择与程序费用身份判断冲突")
                if normalize(old_doc.document_number) != normalize(new_doc.document_number):
                    issues.append("同一提单下的不同账单不能互相覆盖")
                if normalize(old_doc.document_type) != normalize(new_doc.document_type):
                    issues.append("单据类型不一致")
                if not old_doc.document_number or not matched.transaction_party.issuer:
                    issues.append("旧账身份字段不足")
                if getattr(matched, "record_kind", "charge_line") == "legacy_summary":
                    issues.append("历史整单汇总需人工确认，不能自动当作费用明细修改")
                if matched.charge_details.currency != decision.charge_details.currency:
                    issues.append("币种变化必须人工确认")
                for field in ("bill_of_lading", "master_bill_of_lading", "house_bill_of_lading",
                              "booking_number", "container_number", "container_numbers"):
                    incoming = getattr(new_doc, field)
                    previous = getattr(old_doc, field)
                    if incoming and previous and incoming != previous:
                        issues.append(f"单据业务标识存在冲突：{field}")
                for field in ("posting_type",):
                    incoming = getattr(decision.financial_attributes, field)
                    previous = getattr(matched.financial_attributes, field)
                    if incoming and incoming != previous:
                        issues.append(f"财务属性变化需要人工确认：{field}")
                if (decision.charge_details.service_scope and matched.charge_details.service_scope
                    and decision.charge_details.service_scope != matched.charge_details.service_scope):
                    issues.append("费用服务范围不一致")
                if (decision.transaction_party.recipient and matched.transaction_party.recipient
                    and decision.transaction_party.recipient != matched.transaction_party.recipient):
                    issues.append("交易方存在冲突")
            if issues:
                return self._pending(decision, rows, issues, review)
            before = matched.model_dump(mode="json")
            after = matched.model_copy(deep=True)
            patch = {}
            for path in PATCH_FIELDS:
                attr = path.split(".")[1]
                new_value = getattr(decision.charge_details, attr)
                old_value = getattr(matched.charge_details, attr)
                # Missing values mean "not supplied", not deletion.
                if new_value is not None and new_value != old_value:
                    patch[path] = {"old": str(old_value) if isinstance(old_value, Decimal) else old_value,
                                   "new": str(new_value) if isinstance(new_value, Decimal) else new_value}
            if human:
                for field, group in (("issuer", "transaction_party"), ("document_number", "document_info"),
                                     ("posting_type", "financial_attributes")):
                    if review.get(field) and review[field] != getattr(getattr(matched, group), field):
                        patch[f"{group}.{field}"] = {"old": getattr(getattr(matched, group), field),
                                                    "new": review[field]}
            if not patch:
                return self._finished("NO_CHANGE", decision, rows, matched, before, before, {}, review)
            revision_ok = (
                allow_updates and decision.revision_requested and decision.revision_evidence
                and all(evidence_exists(e, sources) for e in decision.revision_evidence)
                and any(re.search(r"修订|更正|改为|调整|修改|revise|correct|amend|change|adjust|updated",
                                  e.original_text, re.I) for e in decision.revision_evidence)
            )
            if not human and not revision_ok:
                return self._pending(decision, rows, ["字段有差异，但缺少已授权的明确修订依据"], review)
            if not human:
                if not decision.field_changes:
                    return self._pending(decision, rows, ["修订必须明确字段补丁"], review)
                if set(decision.field_changes) - PATCH_FIELDS:
                    return self._pending(decision, rows, ["补丁包含禁止修改字段"], review)
                if set(patch) - set(decision.field_changes):
                    return self._pending(decision, rows, ["新材料包含未明确授权的其他差异"], review)
                for path, change in patch.items():
                    supplied = decision.field_changes[path]
                    if isinstance(supplied, dict):
                        supplied = supplied.get("new")
                    if str(supplied) != str(change["new"]):
                        try:
                            equal = Decimal(str(supplied)) == Decimal(str(change["new"]))
                        except Exception:
                            equal = False
                        if not equal:
                            return self._pending(decision, rows, ["补丁与提取事实不一致"], review)
            for path in patch:
                group, field = path.split(".")
                setattr(getattr(after, group), field, getattr(getattr(decision, group), field))
            # Never replace unrelated document, party or financial data.
            if human:
                for field, obj in (("issuer", after.transaction_party), ("document_number", after.document_info),
                                   ("posting_type", after.financial_attributes)):
                    if review.get(field):
                        setattr(obj, field, review[field])
            after.evidence.extend(decision.evidence)
            after.version += 1
            after.updated_at = datetime.now()
            audit = self._audit("UPDATE", decision, before, after.model_dump(mode="json"), patch, review)
            after.audit_history.append(audit)
            after = LedgerRecord.model_validate(after.model_dump())
            return self._finished("UPDATE", decision, rows, matched, before, after.model_dump(mode="json"), patch, review)
        if rows and not human:
            # A different charge on a fully identified invoice can be new; an unconfirmed BL fallback cannot.
            same_doc = all(normalize(r.document_info.document_number) == normalize(decision.document_info.document_number)
                           for r in rows)
            if not same_doc:
                issues.append("业务线索命中其他账单，新增身份尚未确认")
        if not human:
            if not decision.document_info.document_number or not decision.document_info.document_type or not decision.transaction_party.issuer:
                issues.append("新增费用缺少完整单据身份")
        if issues:
            return self._pending(decision, rows, issues, review)
        if named and not review.get("approve_create"):
            return self._pending(decision, rows, ["候选仍有歧义"], review)
        record = LedgerRecord(
            record_id=str(uuid.uuid4()), charge_details=decision.charge_details,
            document_info=decision.document_info, transaction_party=decision.transaction_party,
            financial_attributes=decision.financial_attributes, evidence=decision.evidence,
        )
        record.audit_history.append(self._audit("CREATE", decision, None, record.model_dump(mode="json"), {}, review))
        return self._finished("CREATE", decision, rows, record, None, record.model_dump(mode="json"), {}, review)

    def _audit(self, operation, decision, before, after, patch, review):
        before = {k: v for k, v in before.items() if k != "audit_history"} if before else None
        after = {k: v for k, v in after.items() if k != "audit_history"} if after else None
        return AuditTrail(agent_operation=decision.suggested_operation,
                          agent_reasoning=decision.operation_reasoning, agent_confidence=decision.confidence,
                          program_operation=operation, validation_issues=[], final_operation=operation,
                          conflict_resolution=review.get("note") or "通过身份、证据及变更范围校验",
                          field_changes=patch, old_values=before, new_values=after)

    def _pending(self, decision, candidates, issues, review=None):
        return {"operation": "PENDING_REVIEW", "record_id": None, "expected_version": None,
                "before": None, "after": None, "patch": {},
                "candidates": [r.model_dump(mode="json") for r in candidates],
                "decision": decision.model_dump(mode="json"), "evidence": [e.model_dump(mode="json") for e in decision.evidence],
                "revision_evidence": [e.model_dump(mode="json") for e in decision.revision_evidence],
                "reason": "；".join(dict.fromkeys(issues)), "validation_issues": list(dict.fromkeys(issues)),
                "review": review or {}}

    def _finished(self, operation, decision, candidates, record, before, after, patch, review):
        return {"operation": operation, "record_id": record.record_id,
                "expected_version": record.version if before else None,
                "before": before, "after": after, "patch": patch,
                "candidates": [r.model_dump(mode="json") for r in candidates],
                "decision": decision.model_dump(mode="json"), "evidence": [e.model_dump(mode="json") for e in decision.evidence],
                "revision_evidence": [e.model_dump(mode="json") for e in decision.revision_evidence],
                "reason": {"CREATE": "新费用身份与证据通过校验", "UPDATE": "明确变更已生成字段补丁",
                           "NO_CHANGE": "费用身份及字段一致"}[operation],
                "validation_issues": [], "review": review or {}}

    def decide_and_execute(self, decision, **kwargs):
        """Compatibility entry: returns a plan only; explicit commit is required."""
        return self.plan(decision, **kwargs)
