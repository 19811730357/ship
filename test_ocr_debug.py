"""
OCR 调试测试脚本
直接调用 OCR 功能，方便打断点调试
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from billing_agent.integrations import OCRAdapter
from billing_agent.parsers import DocumentParser
from billing_agent.agent import BillingAgent
from billing_agent.models import Ledger
import json


def test_ocr_direct():
    """测试1: 直接调用 OCR API"""

    print("=" * 70)
    print("测试 1: 直接调用 OCR API")
    print("=" * 70)

    # 👉 在这里打断点，单步执行
    ocr = OCRAdapter()

    # 使用一个公网可访问的 PDF URL
    file_url = "https://example.com/bill.pdf"  # 替换为你的实际文件 URL

    print(f"调用 OCR API: {file_url}")

    try:
        # 👉 在这里打断点，查看 OCR 返回结果
        ocr_result = ocr.process_file(file_url, task="orderChange")

        print("\nOCR API 返回结果:")
        print(json.dumps(ocr_result, indent=2, ensure_ascii=False))

        return ocr_result

    except Exception as e:
        print(f"OCR 调用失败: {e}")
        return None


def test_parser_with_url():
    """测试2: 使用 DocumentParser 解析 URL"""

    print("\n" + "=" * 70)
    print("测试 2: DocumentParser 解析 URL")
    print("=" * 70)

    # 初始化
    ocr_adapter = OCRAdapter()
    parser = DocumentParser(
        ocr_enabled=True,
        ocr_adapter=ocr_adapter
    )

    file_url = "https://example.com/bill.pdf"  # 替换为实际 URL

    print(f"解析文件: {file_url}")

    try:
        # 👉 在这里打断点，单步进入 parse_file_from_url
        result = parser.parse_file_from_url(file_url, file_type='pdf')

        print("\n解析结果:")
        print(f"文件名: {result['source_file']}")
        print(f"类型: {result['source_type']}")
        print(f"内容预览:\n{result['content'][:500]}...")

        return result

    except Exception as e:
        print(f"解析失败: {e}")
        return None


def test_full_workflow_with_url():
    """测试3: 完整工作流（OCR → Agent → 决策）"""

    print("\n" + "=" * 70)
    print("测试 3: 完整工作流 (OCR → Agent → 决策)")
    print("=" * 70)

    # 1. 解析文件
    ocr_adapter = OCRAdapter()
    parser = DocumentParser(
        ocr_enabled=True,
        ocr_adapter=ocr_adapter
    )

    file_url = "https://example.com/bill.pdf"

    try:
        parsed = parser.parse_file_from_url(file_url)
        material_content = parsed['content']

        print(f"✓ 文件解析完成，内容长度: {len(material_content)} 字符")
        print(f"\n内容预览:\n{material_content[:300]}...")

        # 2. 创建 Agent
        agent = BillingAgent(
            accounting_entity="Test Company",
            use_mock=False  # 使用真实 API
        )

        # 3. 创建空账本
        ledger = Ledger(accounting_entity="Test Company")

        print("\n调用 Agent 进行决策...")

        # 👉 在这里打断点，查看传递给模型的内容
        agent_batch = agent.process_material(material_content, ledger)

        print(f"\n✓ Agent 决策完成")
        print(f"决策数: {len(agent_batch.decisions)}")
        print(f"排除项: {len(agent_batch.excluded_items)}")

        # 显示决策
        for i, decision in enumerate(agent_batch.decisions, 1):
            print(f"\n决策 #{i}:")
            print(f"  费用: {decision.charge_details.original_name}")
            print(f"  金额: {decision.charge_details.amount} {decision.charge_details.currency}")
            print(f"  操作: {decision.suggested_operation}")
            print(f"  理由: {decision.operation_reasoning}")
            print(f"  置信度: {decision.confidence}")

        return agent_batch

    except Exception as e:
        print(f"处理失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_with_mock_data():
    """测试4: 使用模拟数据测试数据流"""

    print("\n" + "=" * 70)
    print("测试 4: 使用模拟数据测试")
    print("=" * 70)

    # 模拟 OCR 识别的内容
    mock_ocr_content = """
航运账单

提单号: BL-2024-001
单据号: DN-2024-001

费用明细:
1. 操作费 (HANDLING CHARGE): 50.00 USD
2. 文件费 (DOCUMENTATION FEE): 30.00 USD
3. 码头费 (TERMINAL HANDLING CHARGE): 120.00 USD

付款方式: Prepaid (PP)
签发日期: 2024-10-31
    """

    print("模拟的 OCR 识别内容:")
    print(mock_ocr_content)

    # 创建 Agent
    agent = BillingAgent(
        accounting_entity="Test Company",
        use_mock=False
    )

    # 空账本
    ledger = Ledger(accounting_entity="Test Company")

    print("\n调用 Agent 处理...")

    try:
        # 👉 在这里打断点，查看 Agent 处理过程
        agent_batch = agent.process_material(mock_ocr_content, ledger)

        print(f"\n✓ 处理完成")
        print(f"决策数: {len(agent_batch.decisions)}")

        for i, decision in enumerate(agent_batch.decisions, 1):
            print(f"\n决策 #{i}:")
            print(f"  费用: {decision.charge_details.original_name}")
            print(f"  操作: {decision.suggested_operation}")
            print(f"  理由: {decision.operation_reasoning}")

        return agent_batch

    except Exception as e:
        print(f"处理失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """主函数 - 选择测试场景"""

    print("\n" + "=" * 70)
    print("OCR 调试测试工具")
    print("=" * 70)
    print("\n可用测试:")
    print("1. 直接调用 OCR API (需要文件 URL)")
    print("2. DocumentParser 解析 URL (需要文件 URL)")
    print("3. 完整工作流: OCR → Agent → 决策 (需要文件 URL + API key)")
    print("4. 使用模拟数据测试 (不需要 OCR，只需 API key)")
    print("\n请在下面的代码中选择要运行的测试，然后在相应位置打断点")
    print("=" * 70)

    # ========================================
    # 👉 取消注释你想测试的功能
    # ========================================

    # 测试 1: 直接 OCR
    # test_ocr_direct()

    # 测试 2: Parser + OCR
    # test_parser_with_url()

    # 测试 3: 完整流程 (OCR + Agent)
    # test_full_workflow_with_url()

    # 测试 4: 模拟数据 (推荐：不需要 OCR)
    test_with_mock_data()

    print("\n调试完成！")


if __name__ == "__main__":
    # 👉 在这里打断点开始调试
    main()
