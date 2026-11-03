"""
程序验证器
对模型的决策进行独立验证
"""

from typing import List, Optional
from decimal import Decimal, InvalidOperation
import re

from .models import (
    AgentDecision,
    ValidationResult,
    MatchResult,
    Ledger,
    LedgerRecord,
    ChargeDetails,
    FinancialAttributes
)


def evidence_exists(evidence, source_documents):
    """Verify a quote within its declared immutable source/block."""
    squash = lambda value: " ".join(str(value or "").split())
    if not evidence.original_text.strip():
        return False
    for source in source_documents:
        if evidence.source_id and evidence.source_id != source.get("source_id"):
            continue
        if not evidence.source_id and evidence.source_file != source.get("source_file"):
            continue
        if evidence.block_id:
            texts = [b.get("text", "") for b in source.get("blocks", [])
                     if b.get("block_id") == evidence.block_id
                     and b.get("source_id", source.get("source_id")) == source.get("source_id")]
        else:
            texts = [source.get("content", "")]
        if any(squash(evidence.original_text) in squash(text) for text in texts):
            return True
    return False


def validate_extracted_charge(decision, sources, human_review=False, approved_charge_dictionary=None,
                              allow_unmapped_charges=False):
    issues = []
    charge = decision.charge_details
    if not charge.original_name.strip():
        issues.append("费用名称缺失")
    if not charge.amount.is_finite():
        issues.append("金额必须为有限十进制数")
    elif charge.amount.adjusted() >= 16 or charge.amount.normalize().as_tuple().exponent < -8:
        issues.append("金额超出当前数据库24位总精度/8位小数，不能静默舍入")
    if not charge.currency or not Validator._is_valid_currency(charge.currency):
        issues.append("币种未知或无效")
    if getattr(charge, "amount_role", "line_amount") != "line_amount":
        issues.append("费用金额必须为明细金额，不能使用总额/余额/条件费率")
    if decision.financial_attributes.posting_type not in ("AR", "AP"):
        issues.append("AR/AP交易方向待确认")
    if not charge.standardized_name and not allow_unmapped_charges:
        issues.append("标准费用映射待确认")
    elif charge.standardized_name and not human_review:
        dictionary = CHARGE_NAME_MAPPING if approved_charge_dictionary is None else approved_charge_dictionary
        expected_code = dictionary.get(" ".join(charge.original_name.lower().split()))
        if expected_code != charge.standardized_name:
            issues.append("费用名称未通过适用字典确认，需人工确认映射")
    if not human_review:
        source_ids = {e.source_id for e in decision.evidence if e.source_id}
        source_names = {e.source_file for e in decision.evidence}
        related_text = "\n".join(s.get("content", "") for s in sources
            if s.get("source_id") in source_ids or (not source_ids and s.get("source_file") in source_names))
        squash = lambda value: " ".join(str(value or "").upper().split())
        for label, value in (("单据编号", decision.document_info.document_number),
                             ("签发方", decision.transaction_party.issuer)):
            if value and squash(value) not in squash(related_text):
                issues.append(f"{label}缺少对应来源事实")
        if charge.currency:
            explicit_code = re.search(r"(?<![A-Z])" + re.escape(charge.currency) + r"(?![A-Z])", related_text.upper())
            words = {"USD": "美元", "CNY": "人民币", "EUR": "欧元"}
            if not explicit_code and not (words.get(charge.currency) and words[charge.currency] in related_text):
                issues.append("币种缺少明确原文依据；单独货币符号不能证明币种")
        if not decision.evidence or not all(evidence_exists(e, sources) for e in decision.evidence):
            issues.append("字段证据缺失或无法在指定来源定位")
        else:
            # Presence is necessary, not proof of semantic correctness; retain the full quote for review.
            number_found = False
            from .source_amounts import line_amount_evidence
            for evidence in decision.evidence:
                monetary_field = evidence.field_name in ("amount", "line_amount", "charge_details.amount")
                row_context = (charge.original_name.casefold() in evidence.original_text.casefold()
                               or (charge.currency and charge.currency in evidence.original_text))
                if not monetary_field and not row_context:
                    continue
                if not line_amount_evidence(evidence, decision, sources):
                    if monetary_field:
                        issues.append("总额/余额/单价等汇总费率，或无法确定金额列的多数字原文，不能作为明细金额证据")
                    continue
                for token in re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", evidence.original_text.replace("−", "-")):
                    try:
                        number_found |= Decimal(token.replace(",", "")) == charge.amount
                    except InvalidOperation:
                        pass
            if not number_found:
                issues.append("金额缺少对应数值原文证据")
    if charge.quantity is not None and charge.unit_price is not None:
        calculated = charge.quantity * charge.unit_price
        if calculated != charge.amount:
            issues.append("数量与单价计算不一致；需要明确计价或抵扣规则")
    if charge.line_items:
        if any(i.currency != charge.currency for i in charge.line_items):
            issues.append("禁止跨币种直接合计")
        elif sum((i.amount for i in charge.line_items), Decimal("0")) != charge.amount:
            issues.append("明细合计与声明金额不一致")
    if (getattr(charge, "settlement_amount", None) is None) != (getattr(charge, "settlement_currency", None) is None):
        issues.append("结算金额和结算币种必须同时提供")
    if charge.exchange_rate is not None and (not charge.exchange_rate.is_finite() or charge.exchange_rate <= 0):
        issues.append("汇率必须为原文明示的正有限数")
    return issues


def validate_document_totals(decisions):
    groups = {}
    for decision in decisions:
        doc = decision.document_info
        source_ids = tuple(sorted({e.source_id or e.source_file for e in decision.evidence}))
        key = (doc.document_number, decision.transaction_party.issuer, source_ids)
        groups.setdefault(key, []).append(decision)
    errors = []
    for group in groups.values():
        totals = {d.document_info.document_total for d in group if d.document_info.document_total is not None}
        if not totals:
            continue
        currencies = {d.document_info.total_currency for d in group if d.document_info.document_total is not None}
        if len(totals) != 1 or len(currencies) != 1 or None in currencies:
            errors.append("单据总额或总额币种存在冲突")
            continue
        currency = next(iter(currencies))
        if any(d.charge_details.currency != currency for d in group):
            errors.append("单据总额不能与不同币种的费用直接相加核对")
        elif sum((d.charge_details.amount for d in group), Decimal("0")) != next(iter(totals)):
            calculated = sum((d.charge_details.amount for d in group), Decimal("0"))
            declared = next(iter(totals))
            errors.append(f"单据费用合计与原文总额不一致：明细合计 {calculated} {currency}，单据总额 {declared}，差额 {calculated - declared}")
    return errors


class Validator:
    """验证器：对模型决策进行程序验证"""

    def __init__(self, accounting_entity: str):
        self.accounting_entity = accounting_entity

    def validate_decision(
        self,
        decision: AgentDecision,
        ledger: Ledger
    ) -> ValidationResult:
        """
        验证模型的决策

        Returns:
            ValidationResult: 验证结果，包含问题列表和程序的操作建议
        """
        issues = []
        match_conflicts = []

        # 1. 基础字段验证
        issues.extend(self._validate_basic_fields(decision))

        # 2. 金额和币种验证
        issues.extend(self._validate_amounts(decision.charge_details))

        # 3. AR/AP一致性验证
        issues.extend(self._validate_posting_type(decision.financial_attributes))

        # 4. 程序独立匹配
        program_match = self._independent_match(decision, ledger)

        # 5. 匹配一致性检查
        if decision.matched_record_id != program_match.record_id:
            if decision.matched_record_id and program_match.record_id:
                match_conflicts.append(
                    f"匹配冲突: 模型匹配={decision.matched_record_id}, "
                    f"程序匹配={program_match.record_id}"
                )
            elif decision.matched_record_id and not program_match.matched:
                match_conflicts.append(
                    f"模型匹配了记录{decision.matched_record_id}，但程序未找到匹配"
                )

        # 6. 操作合理性验证
        if decision.suggested_operation == "UPDATE":
            if not decision.matched_record_id:
                issues.append("UPDATE操作必须指定matched_record_id")
            elif not ledger.has_record(decision.matched_record_id):
                issues.append(f"matched_record_id={decision.matched_record_id}不存在于旧账中")

        # 7. 确定程序的操作建议
        program_operation = self._determine_program_operation(
            decision, program_match, issues, match_conflicts
        )

        return ValidationResult(
            is_valid=len(issues) == 0 and len(match_conflicts) == 0,
            program_operation=program_operation,
            program_matched_record_id=program_match.record_id,
            validation_issues=issues,
            match_conflicts=match_conflicts,
            match_result=program_match
        )

    def _validate_basic_fields(self, decision: AgentDecision) -> List[str]:
        """验证基础字段"""
        issues = []

        # 费用名称
        if not decision.charge_details.original_name:
            issues.append("费用名称不能为空")

        # 金额
        if decision.charge_details.amount is None:
            issues.append("金额不能为空")

        # 币种
        if not decision.charge_details.currency:
            issues.append("币种不能为空")
        elif not self._is_valid_currency(decision.charge_details.currency):
            issues.append(f"币种格式无效: {decision.charge_details.currency}")

        # 记账主体一致性
        if decision.financial_attributes.accounting_entity != self.accounting_entity:
            issues.append(
                f"记账主体不一致: 决策={decision.financial_attributes.accounting_entity}, "
                f"当前={self.accounting_entity}"
            )

        return issues

    def _validate_amounts(self, charge: ChargeDetails) -> List[str]:
        """验证金额相关字段"""
        issues = []

        # 金额必须大于0
        if charge.amount is not None and charge.amount <= 0:
            issues.append(f"金额必须大于0: {charge.amount}")

        # 如果有数量和单价，验证计算
        if charge.quantity is not None and charge.unit_price is not None:
            calculated = charge.quantity * charge.unit_price
            # 允许小误差（因为四舍五入）
            if abs(calculated - charge.amount) > Decimal("0.01"):
                issues.append(
                    f"金额计算不符: 数量({charge.quantity}) × 单价({charge.unit_price}) "
                    f"= {calculated} ≠ 金额({charge.amount})"
                )

        return issues

    def _validate_posting_type(self, financial: FinancialAttributes) -> List[str]:
        """验证AR/AP一致性"""
        issues = []

        # 如果给出了posting_type，必须有reasoning
        if financial.posting_type and not financial.posting_type_reasoning:
            issues.append("给出posting_type时必须提供判断依据")

        # 检查posting_type是否为有效值
        if financial.posting_type and financial.posting_type not in ["AR", "AP"]:
            issues.append(f"posting_type只能是AR或AP，当前: {financial.posting_type}")

        return issues

    def _independent_match(
        self,
        decision: AgentDecision,
        ledger: Ledger
    ) -> MatchResult:
        """
        程序独立进行旧账匹配

        匹配层级（从强到弱）：
        1. 单据编号 + 标准费用名称
        2. 提单号 + 标准费用名称 + 币种
        3. 订舱号 + 标准费用名称 + 币种
        4. 箱号 + 原始费用名称 + 金额 + 币种
        """
        doc_info = decision.document_info
        charge = decision.charge_details

        candidates = []

        # 层级1: 单据编号 + 费用名称
        if doc_info.document_number and charge.standardized_name:
            candidates = [
                r for r in ledger.records
                if r.document_info.document_number == doc_info.document_number
                and r.charge_details.standardized_name == charge.standardized_name
            ]
            if len(candidates) == 1:
                return MatchResult(
                    matched=True,
                    record_id=candidates[0].record_id,
                    match_method="document_number + standardized_name",
                    match_confidence="HIGH"
                )
            elif len(candidates) > 1:
                return MatchResult(
                    matched=False,
                    candidates=[r.record_id for r in candidates],
                    match_method="document_number + standardized_name",
                    match_details="找到多个候选，无法唯一匹配"
                )

        # 层级2: 提单号 + 费用名称 + 币种
        if doc_info.bill_of_lading and charge.standardized_name:
            candidates = [
                r for r in ledger.records
                if r.document_info.bill_of_lading == doc_info.bill_of_lading
                and r.charge_details.standardized_name == charge.standardized_name
                and r.charge_details.currency == charge.currency
            ]
            if len(candidates) == 1:
                return MatchResult(
                    matched=True,
                    record_id=candidates[0].record_id,
                    match_method="bill_of_lading + standardized_name + currency",
                    match_confidence="MEDIUM"
                )
            elif len(candidates) > 1:
                return MatchResult(
                    matched=False,
                    candidates=[r.record_id for r in candidates],
                    match_method="bill_of_lading + standardized_name + currency",
                    match_details="找到多个候选，无法唯一匹配"
                )

        # 层级3: 订舱号 + 费用名称 + 币种
        if doc_info.booking_number and charge.standardized_name:
            candidates = [
                r for r in ledger.records
                if r.document_info.booking_number == doc_info.booking_number
                and r.charge_details.standardized_name == charge.standardized_name
                and r.charge_details.currency == charge.currency
            ]
            if len(candidates) == 1:
                return MatchResult(
                    matched=True,
                    record_id=candidates[0].record_id,
                    match_method="booking_number + standardized_name + currency",
                    match_confidence="MEDIUM"
                )
            elif len(candidates) > 1:
                return MatchResult(
                    matched=False,
                    candidates=[r.record_id for r in candidates],
                    match_method="booking_number + standardized_name + currency",
                    match_details="找到多个候选，无法唯一匹配"
                )

        # 层级4: 箱号 + 原始名称 + 金额 + 币种
        if doc_info.container_number:
            candidates = [
                r for r in ledger.records
                if r.document_info.container_number == doc_info.container_number
                and r.charge_details.original_name == charge.original_name
                and r.charge_details.amount == charge.amount
                and r.charge_details.currency == charge.currency
            ]
            if len(candidates) == 1:
                return MatchResult(
                    matched=True,
                    record_id=candidates[0].record_id,
                    match_method="container + original_name + amount + currency",
                    match_confidence="LOW"
                )
            elif len(candidates) > 1:
                return MatchResult(
                    matched=False,
                    candidates=[r.record_id for r in candidates],
                    match_method="container + original_name + amount + currency",
                    match_details="找到多个候选，无法唯一匹配"
                )

        # 未找到匹配
        return MatchResult(
            matched=False,
            match_details="未找到匹配的旧账记录"
        )

    def _determine_program_operation(
        self,
        decision: AgentDecision,
        match_result: MatchResult,
        issues: List[str],
        match_conflicts: List[str]
    ) -> str:
        """确定程序的操作建议"""

        # 如果有验证问题或匹配冲突，转PENDING_REVIEW
        if issues or match_conflicts:
            return "PENDING_REVIEW"

        # 根据匹配结果判断
        if not match_result.matched:
            # 没有旧账匹配
            if match_result.candidates:
                # 有多个候选，无法唯一确定
                return "PENDING_REVIEW"
            else:
                # 确实没有匹配，应该CREATE
                return "CREATE"
        else:
            # 找到唯一匹配
            if decision.suggested_operation == "UPDATE":
                # 模型也建议UPDATE，需要检查是否有实际变化
                return "UPDATE"
            else:
                # 找到匹配但模型没说要UPDATE，可能是NO_CHANGE
                return "NO_CHANGE"

    @staticmethod
    def _is_valid_currency(currency: str) -> bool:
        """验证币种格式（ISO 4217）"""
        if not currency or len(currency) != 3:
            return False
        return currency.isupper() and currency.isalpha()


# ============================================
# 费用名称标准化
# ============================================

# 已知的费用名称映射
CHARGE_NAME_MAPPING = {
    "handling charge": "HANDLING_CHARGE",
    "handling": "HANDLING_CHARGE",
    "操作费": "HANDLING_CHARGE",
    "4 add'l detention free time charge": "DETENTION_FREE_TIME_CHARGE",
    "wharfage": "WHARFAGE",
    "wharfage administration fee": "WHARFAGE_ADMINISTRATION_FEE",

    "documentation fee": "DOCUMENTATION_FEE",
    "doc fee": "DOCUMENTATION_FEE",
    "文件费": "DOCUMENTATION_FEE",

    "terminal handling charge": "THC",
    "thc": "THC",
    "码头操作费": "THC",

    "storage fee": "STORAGE_FEE",
    "storage": "STORAGE_FEE",
    "仓储费": "STORAGE_FEE",

    "demurrage": "DEMURRAGE",
    "滞期费": "DEMURRAGE",
}


def standardize_charge_name(original_name: str) -> Optional[str]:
    """
    标准化费用名称

    Args:
        original_name: 原始费用名称

    Returns:
        标准化名称，如果未知则返回None
    """
    normalized = original_name.lower().strip()
    return CHARGE_NAME_MAPPING.get(normalized)


# ============================================
# 币种标准化
# ============================================

CURRENCY_ALIASES = {
    "usd": "USD",
    "dollar": "USD",
    "美元": "USD",
    "$": "USD",

    "cny": "CNY",
    "rmb": "CNY",
    "人民币": "CNY",
    "¥": "CNY",
    "元": "CNY",

    "eur": "EUR",
    "euro": "EUR",
    "欧元": "EUR",
    "€": "EUR",
}


def standardize_currency(currency: str) -> str:
    """
    标准化币种

    Args:
        currency: 原始币种

    Returns:
        ISO 4217标准币种代码
    """
    normalized = currency.lower().strip()
    return CURRENCY_ALIASES.get(normalized, currency.upper())
