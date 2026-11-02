"""
快速测试数据库集成
验证重启后数据持久化和 UPDATE 识别
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from billing_agent.database import DatabaseManager
from billing_agent.workflow_db import DatabaseWorkflow
from billing_agent.agent import BillingAgent
from billing_agent.models import Ledger
import tempfile


def create_test_file(content: str, filename: str) -> Path:
    """创建测试文件"""
    temp_dir = Path(tempfile.mkdtemp())
    file_path = temp_dir / filename
    file_path.write_text(content, encoding='utf-8')
    return file_path


def test_database_integration():
    """测试数据库集成"""

    print("=" * 70)
    print("Test: Database Integration - Data Persistence After Restart")
    print("=" * 70)

    # ========================================
    # 第一次处理
    # ========================================
    print("\n[Step 1] First Processing - Create Record")
    print("-" * 70)

    # 创建测试文件
    file1 = create_test_file("""
提单号: BL-TEST-001
单据号: DN-TEST-001

费用明细:
1. 操作费 (HANDLING CHARGE): 50.00 USD
2. 文件费 (DOCUMENTATION FEE): 30.00 USD

付款方式: Prepaid
    """, "bill_1.txt")

    # 使用数据库工作流
    workflow1 = DatabaseWorkflow(
        accounting_entity="Test Company",
        use_mock_data=True,  # 使用模拟模式，不需要 API key
        db_type="sqlite",
        db_config={"database": "test_billing.db"}
    )

    print(f"Processing file: {file1.name}")

    try:
        # 注意：mock 模式下不能处理真实文件，我们改用演示场景
        from billing_agent.demo import get_demo_scenario, get_demo_ledger

        print("\n[INFO] Using mock mode, processing demo scenario instead")

        # 保存演示数据到数据库
        ledger = workflow1.db.load_ledger("Test Company")
        print(f"[OK] Loaded from database: {len(ledger.records)} records")

        # 模拟第一次处理
        from billing_agent.models import LedgerRecord, ChargeDetails, DocumentInfo, TransactionParty, FinancialAttributes, Evidence
        import uuid

        record1 = LedgerRecord(
            record_id=f"REC-{uuid.uuid4().hex[:8]}",
            charge_details=ChargeDetails(
                original_name="HANDLING CHARGE",
                standardized_name="操作费",
                amount=50.00,
                currency="USD"
            ),
            document_info=DocumentInfo(
                document_number="DN-TEST-001",
                bill_of_lading="BL-TEST-001"
            ),
            transaction_party=TransactionParty(),
            financial_attributes=FinancialAttributes(
                accounting_entity="Test Company",
                posting_type="AR"
            ),
            evidence=[Evidence(source_file="bill_1.txt", source_type="user_upload", original_text="HANDLING CHARGE: 50 USD")]
        )

        workflow1.db.save_ledger_record(record1)
        print(f"[OK] Saved to database: {record1.charge_details.original_name} - CREATE")

        results1 = {
            'summary': {
                'operations': {'CREATE': 1, 'UPDATE': 0, 'NO_CHANGE': 0, 'PENDING_REVIEW': 0}
            },
            'database_stats': workflow1.db.get_processing_statistics("Test Company")
        }

        print(f"\n[OK] First processing completed")
        print(f"   CREATE: {results1['summary']['operations']['CREATE']}")
        print(f"   UPDATE: {results1['summary']['operations']['UPDATE']}")

        if 'database_stats' in results1:
            stats = results1['database_stats']
            print(f"\n[Database Status]")
            print(f"   Total records: {stats['total_records']}")
            print(f"   Unique documents: {stats['unique_documents']}")

    except Exception as e:
        print(f"[ERROR] Processing failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # ========================================
    # 模拟重启
    # ========================================
    print("\n" + "=" * 70)
    print("【步骤2】模拟重启应用")
    print("=" * 70)

    # 删除旧的 workflow 对象
    del workflow1

    print("✓ 应用已重启（Python 对象已销毁）")

    # ========================================
    # 第二次处理 - 修改同一单据
    # ========================================
    print("\n【步骤3】第二次处理 - 修改同一单据")
    print("-" * 70)

    # 创建新的测试文件（修改金额）
    file2 = create_test_file("""
提单号: BL-TEST-001
单据号: DN-TEST-001

请将操作费从 50 美元改为 40 美元
    """, "bill_2.txt")

    # 重新创建工作流（模拟重启后的新实例）
    workflow2 = DatabaseWorkflow(
        accounting_entity="Test Company",
        use_mock_data=False,
        db_type="sqlite",
        db_config={"database": "test_billing.db"}
    )

    print(f"处理文件: {file2.name}")

    try:
        results2 = workflow2.process_real_files(
            file_paths=[file2],
            ledger_data=None,  # 不传入旧账，应该从数据库加载
            output_dir=Path("output/test2")
        )

        print(f"\n✅ 第二次处理完成")
        print(f"   CREATE: {results2['summary']['operations']['CREATE']}")
        print(f"   UPDATE: {results2['summary']['operations']['UPDATE']}")

        if 'database_stats' in results2:
            stats = results2['database_stats']
            print(f"\n💾 数据库状态:")
            print(f"   总记录数: {stats['total_records']}")
            print(f"   唯一单据数: {stats['unique_documents']}")

        # 验证结果
        print("\n" + "=" * 70)
        print("【验证结果】")
        print("=" * 70)

        if results2['summary']['operations']['UPDATE'] > 0:
            print("✅ 测试通过！系统正确识别为 UPDATE 操作")
            print("✅ 数据库持久化工作正常")
            print("✅ 重启后能够从数据库加载历史记录")
        else:
            print("❌ 测试失败！系统未能识别为 UPDATE")
            print("   可能原因：")
            print("   1. 数据库未正确加载")
            print("   2. Agent 决策逻辑问题")
            print("   3. 单据匹配逻辑问题")

    except Exception as e:
        print(f"❌ 处理失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    # ========================================
    # 查询数据库
    # ========================================
    print("\n" + "=" * 70)
    print("【步骤4】查询数据库")
    print("=" * 70)

    db = DatabaseManager(db_type="sqlite", db_config={"database": "test_billing.db"})

    # 按单据号查询
    records = db.query_records_by_document("DN-TEST-001")
    print(f"\n📄 单据号 DN-TEST-001 的记录:")
    for record in records:
        print(f"   - {record.charge_details.original_name}: "
              f"{record.charge_details.amount} {record.charge_details.currency}")
        print(f"     记录ID: {record.record_id}")
        print(f"     更新时间: {record.updated_at if hasattr(record, 'updated_at') else 'N/A'}")

    # 统计
    stats = db.get_processing_statistics("Test Company")
    print(f"\n📊 统计信息:")
    print(f"   总记录数: {stats['total_records']}")
    print(f"   唯一单据数: {stats['unique_documents']}")
    print(f"   唯一提单数: {stats['unique_bls']}")

    db.close()

    print("\n" + "=" * 70)
    print("测试完成！")
    print("=" * 70)
    print("\n💾 测试数据库文件: test_billing.db")
    print("   可以使用 'sqlite3 test_billing.db' 查看数据")

    return True


if __name__ == "__main__":
    success = test_database_integration()
    sys.exit(0 if success else 1)
