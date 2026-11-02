"""
程序级别的智能 CRUD 决策
不依赖 LLM 记忆，而是在执行前由程序检索和判断
"""

from typing import Optional, Dict, Any
from .models import LedgerRecord, AgentDecision
from .database import DatabaseManager


class SmartCRUDExecutor:
    """智能 CRUD 执行器 - 程序级别判断操作类型"""

    def __init__(self, db: DatabaseManager, accounting_entity: str):
        self.db = db
        self.accounting_entity = accounting_entity

    def decide_and_execute(self, decision: AgentDecision) -> Dict[str, Any]:
        """
        根据单据号智能决定操作类型并执行

        流程：
        1. 模型只给出费用信息（不需要判断 CREATE/UPDATE）
        2. 程序根据单据号检索数据库
        3. 程序判断是 CREATE 还是 UPDATE
        4. 验证金额一致性
        5. 执行相应操作

        Args:
            decision: Agent 决策（包含费用信息）

        Returns:
            执行结果 {"operation": "CREATE|UPDATE", "record_id": "...", ...}
        """

        # 提取关键信息
        document_number = decision.document_info.document_number
        bill_of_lading = decision.document_info.bill_of_lading
        charge_name = decision.charge_details.original_name
        new_amount = decision.charge_details.amount

        print(f"\n[CRUD Executor] Processing: {charge_name}")
        print(f"  Document: {document_number or 'N/A'}")
        print(f"  BL: {bill_of_lading or 'N/A'}")
        print(f"  Amount: {new_amount} {decision.charge_details.currency}")

        # ========================================
        # 验证：金额一致性检查
        # ========================================
        validation_result = self._validate_amount_consistency(decision)
        if not validation_result["is_valid"]:
            print(f"  ⚠️  Amount validation failed: {validation_result['reason']}")
            print(f"  → Decision: PENDING_REVIEW (需人工审核)")
            return {
                "operation": "PENDING_REVIEW",
                "record_id": None,
                "reason": validation_result['reason'],
                "validation_issues": validation_result['details']
            }

        # ========================================
        # 步骤1：检索数据库中的相关记录
        # ========================================
        existing_records = self._search_existing_records(
            document_number=document_number,
            bill_of_lading=bill_of_lading,
            charge_name=charge_name
        )

        if not existing_records:
            # 没有找到匹配记录 → CREATE
            print(f"  → Decision: CREATE (no existing record found)")
            return self._execute_create(decision)

        # ========================================
        # 步骤2：智能匹配最佳记录
        # ========================================
        matched_record = self._find_best_match(
            existing_records=existing_records,
            document_number=document_number,
            bill_of_lading=bill_of_lading,
            charge_name=charge_name,
            new_amount=new_amount
        )

        if not matched_record:
            # 找到记录但无法唯一匹配 → CREATE（保守策略）
            print(f"  → Decision: CREATE (multiple matches, cannot determine uniquely)")
            return self._execute_create(decision)

        # ========================================
        # 步骤3：比较数据，判断是否需要更新
        # ========================================
        has_changes = self._detect_changes(matched_record, decision)

        if not has_changes:
            # 数据完全相同 → NO_CHANGE
            print(f"  → Decision: NO_CHANGE (data is identical)")
            return {
                "operation": "NO_CHANGE",
                "record_id": matched_record.record_id,
                "matched_record": matched_record,
                "reason": "Data is identical to existing record"
            }

        # 有变化 → UPDATE
        print(f"  → Decision: UPDATE (found changes)")
        print(f"     Old amount: {matched_record.charge_details.amount}")
        print(f"     New amount: {new_amount}")
        return self._execute_update(decision, matched_record)

    def _search_existing_records(
        self,
        document_number: Optional[str],
        bill_of_lading: Optional[str],
        charge_name: str
    ) -> list[LedgerRecord]:
        """检索数据库中的相关记录"""

        records = []

        # 优先级1：按单据号查询
        if document_number:
            records = self.db.query_records_by_document(document_number)
            if records:
                print(f"  [Search] Found {len(records)} records by document_number")
                return records

        # 优先级2：按提单号查询
        if bill_of_lading:
            records = self.db.query_records_by_bl(bill_of_lading)
            if records:
                print(f"  [Search] Found {len(records)} records by bill_of_lading")
                return records

        # 没有找到
        print(f"  [Search] No existing records found")
        return []

    def _find_best_match(
        self,
        existing_records: list[LedgerRecord],
        document_number: Optional[str],
        bill_of_lading: Optional[str],
        charge_name: str,
        new_amount: float = None
    ) -> Optional[LedgerRecord]:
        """从多条记录中找到最佳匹配"""

        if len(existing_records) == 0:
            return None

        # 始终按费用名称过滤（即使只有一条记录）
        matched_by_name = [
            r for r in existing_records
            if r.charge_details.original_name.upper() == charge_name.upper()
        ]

        if len(matched_by_name) == 1:
            # 找到唯一匹配
            print(f"  [Match] Unique match found: {matched_by_name[0].record_id}")
            return matched_by_name[0]

        if len(matched_by_name) == 0:
            # 没有费用名称匹配的，这是新费用
            print(f"  [Match] No records match charge name: {charge_name}")
            return None

        # 多条同名记录，需要进一步区分
        print(f"  [Match] Multiple records ({len(matched_by_name)}) match charge name: {charge_name}")

        # 尝试按金额匹配（用于识别真正的更新）
        if new_amount is not None:
            matched_by_amount = [
                r for r in matched_by_name
                if abs(r.charge_details.amount - new_amount) < 0.01  # 允许小数误差
            ]

            if len(matched_by_amount) == 1:
                print(f"  [Match] Matched by amount: {matched_by_amount[0].record_id}")
                return matched_by_amount[0]

        # 无法唯一确定
        print(f"  [Match] Cannot determine uniquely")
        return None

    def _detect_changes(self, old_record: LedgerRecord, decision: AgentDecision) -> bool:
        """检测数据是否有变化"""

        # 比较金额
        if old_record.charge_details.amount != decision.charge_details.amount:
            return True

        # 比较币种
        if old_record.charge_details.currency != decision.charge_details.currency:
            return True

        # 比较付款方式
        if old_record.charge_details.payment_method != decision.charge_details.payment_method:
            return True

        # 比较标准名称
        if old_record.charge_details.standardized_name != decision.charge_details.standardized_name:
            return True

        # 没有变化
        return False

    def _execute_create(self, decision: AgentDecision) -> Dict[str, Any]:
        """执行 CREATE 操作"""
        import uuid

        record = LedgerRecord(
            record_id=f"REC-{uuid.uuid4().hex[:8]}",
            charge_details=decision.charge_details,
            document_info=decision.document_info,
            transaction_party=decision.transaction_party,
            financial_attributes=decision.financial_attributes
        )

        self.db.save_ledger_record(record)

        return {
            "operation": "CREATE",
            "record_id": record.record_id,
            "record": record,
            "reason": "New record created"
        }

    def _execute_update(self, decision: AgentDecision, old_record: LedgerRecord) -> Dict[str, Any]:
        """执行 UPDATE 操作"""

        # 保持原 record_id，更新数据
        updated_record = LedgerRecord(
            record_id=old_record.record_id,  # 保持不变
            charge_details=decision.charge_details,
            document_info=decision.document_info,
            transaction_party=decision.transaction_party,
            financial_attributes=decision.financial_attributes
        )

        self.db.save_ledger_record(updated_record)

        return {
            "operation": "UPDATE",
            "record_id": updated_record.record_id,
            "old_record": old_record,
            "new_record": updated_record,
            "reason": "Record updated with new data"
        }

    def _validate_amount_consistency(self, decision: AgentDecision) -> Dict[str, Any]:
        """
        验证金额一致性

        检查：
        1. 如果有 line_items，计算总和是否与 amount 一致
        2. 允许小数误差（0.01）

        Returns:
            {"is_valid": bool, "reason": str, "details": dict}
        """
        line_items = decision.charge_details.line_items

        # 如果没有明细项，跳过验证
        if not line_items:
            return {"is_valid": True, "reason": "No line items to validate"}

        # 计算明细项总和
        calculated_total = sum(item.amount for item in line_items)
        declared_total = decision.charge_details.amount

        # 允许0.01的误差（处理浮点数精度问题）
        difference = abs(float(calculated_total) - float(declared_total))

        print(f"  [Validation] Amount consistency check:")
        print(f"    Declared total: {declared_total}")
        print(f"    Calculated total (from {len(line_items)} items): {calculated_total}")
        print(f"    Difference: {difference}")

        if difference > 0.01:
            # 金额不一致
            return {
                "is_valid": False,
                "reason": f"金额不一致：账单总额 {declared_total}，明细合计 {calculated_total}，差额 {difference}",
                "details": {
                    "declared_total": float(declared_total),
                    "calculated_total": float(calculated_total),
                    "difference": difference,
                    "line_items_count": len(line_items)
                }
            }

        print(f"    ✅ Amounts match (within tolerance)")
        return {"is_valid": True, "reason": "Amounts are consistent"}
