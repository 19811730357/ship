"""Explicit bookkeeping rules applied after a unique old charge is selected."""
import re


POSTING_POLICY_VERSION = "posting-policy-v1"

# Only exact, known missing-field messages can be released without a structured code.
MISSING_FIELD_MESSAGES = {
    "AR/AP交易方向待确认": "POSTING_TYPE_MISSING",
    "AR/AP交易方向不明": "POSTING_TYPE_MISSING",
    "标准费用映射待确认": "CHARGE_MAPPING_UNKNOWN",
    "新增费用缺少完整单据身份": "DOCUMENT_IDENTITY_MISSING",
    "单据身份待确认": "DOCUMENT_IDENTITY_MISSING",
}


def apply_posting_policy(financial, matched, default_posting_type):
    """Preserve explicit values, inherit old directions, then apply a configured default."""
    warnings = []
    if financial.posting_type and financial.posting_type_origin not in ("default", "model_inferred"):
        return warnings
    previous = matched.financial_attributes if matched else None
    if previous and previous.posting_type in ("AR", "AP"):
        financial.posting_type = previous.posting_type
        financial.posting_type_origin = "inherited"
        financial.policy_version = POSTING_POLICY_VERSION
        financial.posting_type_reasoning = f"继承已匹配旧账 {matched.record_id} 的 {previous.posting_type} 方向"
    elif financial.posting_type and financial.posting_type_origin == "model_inferred":
        # For a new fee keep the model's document-role inference, without pretending it is explicit.
        return warnings
    elif default_posting_type:
        financial.posting_type = default_posting_type
        financial.posting_type_origin = "default"
        financial.policy_version = POSTING_POLICY_VERSION
        financial.posting_type_reasoning = f"材料未明确交易方向，按当前记账主体配置默认使用 {default_posting_type}"
        warnings.append({"code": "POSTING_TYPE_DEFAULTED", "severity": "warning",
                         "message": financial.posting_type_reasoning, "origin": "policy",
                         "policy_version": POSTING_POLICY_VERSION})
    elif financial.posting_type_origin == "default":
        # A model's default is not an enabled application rule.
        financial.posting_type = None
        financial.posting_type_origin = None
        financial.posting_type_reasoning = None
        financial.policy_version = None
    return warnings


def unresolved_model_review(decision, mapping_resolved):
    """Recompute only known missing-field blockers; retain every other model concern."""
    if decision.suggested_operation != "PENDING_REVIEW" and not decision.review_issues:
        return [], []
    reported = decision.review_issues
    if not reported:
        reasons = [text.strip() for text in re.split(r"[;；\n]+", decision.operation_reasoning) if text.strip()]
        reported = [{"code": MISSING_FIELD_MESSAGES.get(text), "message": text} for text in reasons]
    blockers, resolved = [], []
    for issue in reported:
        code = issue.get("code")
        message = str(issue.get("message") or issue.get("description") or issue.get("error") or code or "模型要求复核")
        done = (code == "POSTING_TYPE_MISSING" and decision.financial_attributes.posting_type in ("AR", "AP"))
        done |= code == "CHARGE_MAPPING_UNKNOWN" and mapping_resolved
        done |= (code == "DOCUMENT_IDENTITY_MISSING" and
                 bool(decision.document_info.document_number and decision.document_info.document_type
                      and decision.transaction_party.issuer))
        if done:
            status = "resolved_by_reextraction" if code == "DOCUMENT_IDENTITY_MISSING" else "resolved_by_policy"
            resolved.append({"code": code, "message": message, "status": status,
                             "origin": "policy", "policy_version": POSTING_POLICY_VERSION})
        else:
            blockers.append("模型报告待复核：" + message)
    if not reported:
        blockers.append("模型报告待复核：" + decision.operation_reasoning)
    return blockers, resolved
