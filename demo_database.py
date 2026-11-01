"""
使用数据库的工作流示例
解决重启后数据丢失的问题
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from billing_agent.database import DatabaseManager
from billing_agent.workflow import BillingWorkflow
from billing_agent.parsers import DocumentParser
from billing_agent.agent import BillingAgent
import uuid


def demo_with_database():
    """演示：使用数据库实现持久化"""

    print("=" * 70)
    print("演示：数据库持久化 - 解决重启问题")
    print("=" * 70)

    # 1. 初始化数据库
    db = DatabaseManager(db_type="sqlite", db_config={"database": "billing.db"})

    accounting_entity = "Demo Company"

    # ========================================
    # 场景1：第一次处理 - BL-2024-001 操作费 50 USD
    # ========================================
    print("\n【场景1】第一次处理单据")
    print("-" * 70)

    # 从数据库加载旧账（第一次是空的）
    ledger = db.load_ledger(accounting_entity)
    print(f"当前账本记录数: {len(ledger.records)}")

    # 模拟第一次处理
    mock_content_1 = """
提单号: BL-2024-001
单据号: DN-2024-001

费用明细:
1. 操作费 (HANDLING CHARGE): 50.00 USD
付款方式: Prepaid
    """

    agent = BillingAgent(accounting_entity=accounting_entity, use_mock=False)

    print("\n处理第一份材料...")
    try:
        # Agent 决策
        agent_batch = agent.process_material(mock_content_1, ledger)

        session_id = str(uuid.uuid4())

        # 保存处理结果到数据库
        for decision in agent_batch.decisions:
            # 创建 LedgerRecord
            from billing_agent.models import LedgerRecord
            record = LedgerRecord(
                record_id=f"REC-{uuid.uuid4().hex[:8]}",
                charge_details=decision.charge_details,
                document_info=decision.document_info,
                transaction_party=decision.transaction_party,
                financial_attributes=decision.financial_attributes,
                evidence=decision.evidence
            )

            # 保存到数据库
            db.save_ledger_record(record)

            # 保存处理历史
            db.save_processing_history(
                session_id=session_id,
                operation=decision.suggested_operation,
                record_id=record.record_id,
                model_suggestion=decision.suggested_operation,
                model_confidence=decision.confidence,
                model_reasoning=decision.operation_reasoning,
                program_validation="APPROVED",
                final_decision=decision.suggested_operation,
                decision_data=decision.model_dump()
            )

            print(f"✓ 已保存: {record.charge_details.original_name} - {decision.suggested_operation}")

    except Exception as e:
        print(f"处理失败: {e}")

    # ========================================
    # 模拟重启应用
    # ========================================
    print("\n" + "=" * 70)
    print("【模拟重启应用】")
    print("=" * 70)

    # 重新连接数据库
    db2 = DatabaseManager(db_type="sqlite", db_config={"database": "billing.db"})

    # ========================================
    # 场景2：第二次处理 - 同一单据，修改金额为 30 USD
    # ========================================
    print("\n【场景2】第二次处理（修改金额）")
    print("-" * 70)

    # 从数据库加载旧账（现在有数据了！）
    ledger2 = db2.load_ledger(accounting_entity)
    print(f"从数据库加载的账本记录数: {len(ledger2.records)}")

    for record in ledger2.records:
        print(f"  - {record.charge_details.original_name}: "
              f"{record.charge_details.amount} {record.charge_details.currency} "
              f"(单据号: {record.document_info.document_number})")

    # 第二次处理：修改金额
    mock_content_2 = """
提单号: BL-2024-001
单据号: DN-2024-001

请将操作费从 50 美元改为 30 美元
    """

    print("\n处理第二份材料...")
    try:
        agent2 = BillingAgent(accounting_entity=accounting_entity, use_mock=False)
        agent_batch2 = agent2.process_material(mock_content_2, ledger2)

        for decision in agent_batch2.decisions:
            print(f"✓ 模型判断: {decision.suggested_operation}")
            print(f"  理由: {decision.operation_reasoning}")
            print(f"  匹配记录: {decision.matched_record_id}")

            # 如果是 UPDATE，更新数据库中的记录
            if decision.suggested_operation == "UPDATE" and decision.matched_record_id:
                # 查找并更新记录
                old_record = ledger2.get_record(decision.matched_record_id)
                if old_record:
                    # 创建更新后的记录
                    updated_record = LedgerRecord(
                        record_id=old_record.record_id,
                        charge_details=decision.charge_details,
                        document_info=decision.document_info,
                        transaction_party=decision.transaction_party,
                        financial_attributes=decision.financial_attributes,
                        evidence=decision.evidence
                    )
                    db2.save_ledger_record(updated_record)
                    print(f"✓ 已更新数据库记录")

    except Exception as e:
        print(f"处理失败: {e}")

    # ========================================
    # 查询统计
    # ========================================
    print("\n" + "=" * 70)
    print("【数据库统计】")
    print("=" * 70)

    stats = db2.get_processing_statistics(accounting_entity)
    print(f"总记录数: {stats['total_records']}")
    print(f"唯一单据数: {stats['unique_documents']}")
    print(f"唯一提单数: {stats['unique_bls']}")

    # 查询特定单据的历史
    print("\n按单据号查询:")
    records_by_doc = db2.query_records_by_document("DN-2024-001")
    for record in records_by_doc:
        print(f"  - {record.charge_details.original_name}: "
              f"{record.charge_details.amount} {record.charge_details.currency}")

    db.close()
    db2.close()


if __name__ == "__main__":
    demo_with_database()
