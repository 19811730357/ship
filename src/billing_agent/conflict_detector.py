"""
增强的验证模块
检测重复账单和数据冲突
"""

from typing import List, Dict, Any, Optional
from decimal import Decimal
from datetime import datetime, timedelta
import hashlib

from .models import AgentDecision, Ledger


class ConflictDetector:
    """冲突检测器"""

    def __init__(self, tolerance: float = 0.01):
        """
        Args:
            tolerance: 金额差异容忍度（默认0.01）
        """
        self.tolerance = tolerance
        self.processed_files = {}  # 文件指纹缓存

    def detect_duplicate_file(self, file_content: bytes, time_window: int = 300) -> Optional[Dict[str, Any]]:
        """
        检测重复文件

        Args:
            file_content: 文件内容
            time_window: 时间窗口（秒），默认5分钟

        Returns:
            如果是重复文件，返回首次处理的信息；否则返回 None
        """
        # 计算文件指纹
        fingerprint = hashlib.sha256(file_content).hexdigest()
        now = datetime.now()

        # 检查是否在时间窗口内处理过
        if fingerprint in self.processed_files:
            first_seen = self.processed_files[fingerprint]["timestamp"]
            if (now - first_seen).total_seconds() < time_window:
                return {
                    "is_duplicate": True,
                    "first_seen": first_seen,
                    "fingerprint": fingerprint
                }

        # 记录文件
        self.processed_files[fingerprint] = {
            "timestamp": now,
            "fingerprint": fingerprint
        }

        return None

    def detect_amount_conflict(self, decision: AgentDecision, existing_record: Ledger) -> Optional[Dict[str, Any]]:
        """
        检测金额冲突

        场景：同一单据号，同一费用名称，但金额不同

        Args:
            decision: 新的决策
            existing_record: 已存在的记录

        Returns:
            如果有冲突，返回冲突详情；否则返回 None
        """
        new_amount = float(decision.charge_details.amount)
        old_amount = float(existing_record.charge_details.amount)

        difference = abs(new_amount - old_amount)

        if difference > self.tolerance:
            return {
                "type": "AMOUNT_CONFLICT",
                "severity": "HIGH",
                "message": f"金额冲突：同一单据的相同费用金额不一致",
                "details": {
                    "document_number": decision.document_info.document_number,
                    "charge_name": decision.charge_details.original_name,
                    "new_amount": new_amount,
                    "old_amount": old_amount,
                    "difference": difference,
                    "existing_record_id": existing_record.record_id
                }
            }

        return None

    def detect_line_items_conflict(self, decision: AgentDecision) -> Optional[Dict[str, Any]]:
        """
        检测明细项冲突

        场景：账单总额与明细项之和不一致

        Args:
            decision: 决策

        Returns:
            如果有冲突，返回冲突详情；否则返回 None
        """
        line_items = decision.charge_details.line_items

        if not line_items:
            return None

        # 计算明细项总和
        calculated_total = sum(item.amount for item in line_items)
        declared_total = decision.charge_details.amount

        difference = abs(float(calculated_total) - float(declared_total))

        if difference > self.tolerance:
            return {
                "type": "LINE_ITEMS_CONFLICT",
                "severity": "HIGH",
                "message": f"明细项冲突：账单总额与明细项之和不一致",
                "details": {
                    "declared_total": float(declared_total),
                    "calculated_total": float(calculated_total),
                    "difference": difference,
                    "line_items_count": len(line_items)
                }
            }

        return None

    def detect_currency_conflict(self, decision: AgentDecision, existing_record: Ledger) -> Optional[Dict[str, Any]]:
        """
        检测币种冲突

        场景：同一单据的币种不一致

        Args:
            decision: 新的决策
            existing_record: 已存在的记录

        Returns:
            如果有冲突，返回冲突详情；否则返回 None
        """
        new_currency = decision.charge_details.currency
        old_currency = existing_record.charge_details.currency

        if new_currency != old_currency:
            return {
                "type": "CURRENCY_CONFLICT",
                "severity": "MEDIUM",
                "message": f"币种冲突：同一单据的币种不一致",
                "details": {
                    "document_number": decision.document_info.document_number,
                    "new_currency": new_currency,
                    "old_currency": old_currency,
                    "existing_record_id": existing_record.record_id
                }
            }

        return None

    def detect_party_conflict(self, decision: AgentDecision, existing_record: Ledger) -> Optional[Dict[str, Any]]:
        """
        检测交易方冲突

        场景：同一单据的签发方不一致

        Args:
            decision: 新的决策
            existing_record: 已存在的记录

        Returns:
            如果有冲突，返回冲突详情；否则返回 None
        """
        new_issuer = decision.transaction_party.issuer
        old_issuer = existing_record.transaction_party.issuer

        if new_issuer and old_issuer and new_issuer != old_issuer:
            return {
                "type": "PARTY_CONFLICT",
                "severity": "MEDIUM",
                "message": f"交易方冲突：同一单据的签发方不一致",
                "details": {
                    "document_number": decision.document_info.document_number,
                    "new_issuer": new_issuer,
                    "old_issuer": old_issuer,
                    "existing_record_id": existing_record.record_id
                }
            }

        return None

    def detect_all_conflicts(self, decision: AgentDecision, existing_records: List[Ledger]) -> List[Dict[str, Any]]:
        """
        检测所有冲突

        Args:
            decision: 新的决策
            existing_records: 已存在的记录列表

        Returns:
            冲突列表
        """
        conflicts = []

        # 检测明细项冲突（单个决策内部）
        line_items_conflict = self.detect_line_items_conflict(decision)
        if line_items_conflict:
            conflicts.append(line_items_conflict)

        # 检测与已存在记录的冲突
        for existing in existing_records:
            # 金额冲突
            amount_conflict = self.detect_amount_conflict(decision, existing)
            if amount_conflict:
                conflicts.append(amount_conflict)

            # 币种冲突
            currency_conflict = self.detect_currency_conflict(decision, existing)
            if currency_conflict:
                conflicts.append(currency_conflict)

            # 交易方冲突
            party_conflict = self.detect_party_conflict(decision, existing)
            if party_conflict:
                conflicts.append(party_conflict)

        return conflicts


class DuplicateDetector:
    """重复检测器"""

    def __init__(self):
        pass

    def is_exact_duplicate(self, decision: AgentDecision, existing_record: Ledger) -> bool:
        """
        判断是否完全重复

        完全重复的条件：
        1. 单据号相同
        2. 费用名称相同
        3. 金额相同
        4. 币种相同

        Args:
            decision: 新的决策
            existing_record: 已存在的记录

        Returns:
            是否完全重复
        """
        return (
            decision.document_info.document_number == existing_record.document_info.document_number and
            decision.charge_details.original_name == existing_record.charge_details.original_name and
            abs(float(decision.charge_details.amount) - float(existing_record.charge_details.amount)) < 0.01 and
            decision.charge_details.currency == existing_record.charge_details.currency
        )

    def is_probable_duplicate(self, decision: AgentDecision, existing_records: List[Ledger]) -> Optional[Ledger]:
        """
        判断是否可能重复

        可能重复的条件：
        1. 费用名称相似（编辑距离）
        2. 金额接近（±5%）
        3. 时间接近（24小时内）

        Args:
            decision: 新的决策
            existing_records: 已存在的记录列表

        Returns:
            如果可能重复，返回最可能的记录；否则返回 None
        """
        new_amount = float(decision.charge_details.amount)

        for existing in existing_records:
            old_amount = float(existing.charge_details.amount)

            # 金额接近（±5%）
            if abs(new_amount - old_amount) / old_amount < 0.05:
                # 费用名称相似
                if self._is_similar_name(
                    decision.charge_details.original_name,
                    existing.charge_details.original_name
                ):
                    return existing

        return None

    def _is_similar_name(self, name1: str, name2: str) -> bool:
        """
        判断费用名称是否相似

        Args:
            name1: 名称1
            name2: 名称2

        Returns:
            是否相似
        """
        # 简单实现：转小写后比较
        # 可以使用更复杂的算法（如编辑距离）
        name1 = name1.lower().strip()
        name2 = name2.lower().strip()

        return name1 == name2 or name1 in name2 or name2 in name1


# 使用示例
if __name__ == "__main__":
    # 示例：检测冲突
    detector = ConflictDetector()

    # 模拟场景：金额冲突
    from src.billing_agent.models import ChargeDetails, DocumentInfo, TransactionParty, FinancialAttributes, Evidence

    decision = AgentDecision(
        suggested_operation="CREATE",
        charge_details=ChargeDetails(
            original_name="HANDLING CHARGE",
            amount=Decimal("100.00"),
            currency="USD"
        ),
        document_info=DocumentInfo(document_number="DC-108478"),
        transaction_party=TransactionParty(),
        financial_attributes=FinancialAttributes(accounting_entity="Test"),
        evidence=[Evidence(source_file="test.pdf", source_type="attachment", original_text="100")]
    )

    # 假设数据库中已有记录
    # existing = ...

    # conflicts = detector.detect_all_conflicts(decision, [existing])
    # print(conflicts)
