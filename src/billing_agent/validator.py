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
