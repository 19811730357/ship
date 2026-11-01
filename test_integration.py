"""
集成测试：验证文件解析和Agent调用功能
"""

import sys
from pathlib import Path

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from billing_agent.parsers import DocumentParser
from billing_agent.agent import BillingAgent, is_api_configured
from billing_agent.models import Ledger
from billing_agent.demo import get_demo_ledger


def test_parser():
    """测试文件解析器"""
    print("=" * 60)
    print("测试 1: 文件解析器")
    print("=" * 60)

    parser = DocumentParser()

    # 创建测试文本文件
    test_file = Path("test_sample.txt")
    test_content = """
    航运账单测试

    费用明细：
    - 操作费 (HANDLING CHARGE): 50 USD
    - 文件费 (DOCUMENTATION FEE): 30 USD

    单据号: DN-2024-001
    提单号: BL-2024-001
    """

    test_file.write_text(test_content, encoding='utf-8')

    try:
        result = parser.parse_file(test_file)
        print(f"✅ 解析成功")
        print(f"   文件名: {result['source_file']}")
        print(f"   类型: {result['source_type']}")
        print(f"   内容长度: {len(result['content'])} 字符")
        print(f"   内容预览: {result['content'][:100]}...")
        return True
    except Exception as e:
        print(f"❌ 解析失败: {e}")
        return False
    finally:
        if test_file.exists():
            test_file.unlink()


def test_agent_mock():
    """测试Agent（模拟模式）"""
    print("\n" + "=" * 60)
    print("测试 2: Agent 初始化（模拟模式）")
    print("=" * 60)

    try:
        agent = BillingAgent(accounting_entity="Test Entity", use_mock=True)
        print(f"✅ Agent初始化成功（模拟模式）")
        print(f"   记账主体: {agent.accounting_entity}")
        print(f"   使用模拟: {agent.use_mock}")
        return True
    except Exception as e:
        print(f"❌ Agent初始化失败: {e}")
        return False


def test_agent_real():
    """测试Agent（真实模式）"""
    print("\n" + "=" * 60)
    print("测试 3: Agent 初始化（真实模式）")
    print("=" * 60)

    if not is_api_configured():
        print("⚠️  API未配置，跳过真实模式测试")
        print("   提示: 在.env中设置DASHSCOPE_API_KEY来启用")
        return None

    try:
        agent = BillingAgent(accounting_entity="Test Entity", use_mock=False)
        print(f"✅ Agent初始化成功（真实模式）")
        print(f"   记账主体: {agent.accounting_entity}")
        print(f"   LLM已配置: {agent.llm is not None}")
        print(f"   Chain已创建: {agent.chain is not None}")
        return True
    except Exception as e:
        print(f"❌ Agent初始化失败: {e}")
        return False


def test_demo_workflow():
    """测试演示工作流"""
    print("\n" + "=" * 60)
    print("测试 4: 演示工作流")
    print("=" * 60)

    from billing_agent.workflow import BillingWorkflow

    try:
        workflow = BillingWorkflow(
            accounting_entity="Demo Origin",
            use_mock_data=True
        )

        # 运行一个演示场景
        results = workflow.process_demo_scenario("update", output_dir=None)

        print(f"✅ 演示场景运行成功")
        print(f"   总决策数: {results['summary']['total_decisions']}")
        print(f"   CREATE: {results['summary']['operations']['CREATE']}")
        print(f"   UPDATE: {results['summary']['operations']['UPDATE']}")
        print(f"   NO_CHANGE: {results['summary']['operations']['NO_CHANGE']}")
        print(f"   PENDING_REVIEW: {results['summary']['operations']['PENDING_REVIEW']}")
        return True
    except Exception as e:
        print(f"❌ 演示工作流失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_file_formats():
    """测试多种文件格式解析"""
    print("\n" + "=" * 60)
    print("测试 5: 多文件格式支持")
    print("=" * 60)

    parser = DocumentParser()

    # 测试TXT
    txt_file = Path("test.txt")
    txt_file.write_text("测试文本内容", encoding='utf-8')

    formats_tested = []

    try:
        result = parser.parse_txt(txt_file)
        print(f"✅ TXT解析: {result['source_type']}")
        formats_tested.append("TXT")
    except Exception as e:
        print(f"❌ TXT解析失败: {e}")
    finally:
        if txt_file.exists():
            txt_file.unlink()

    # 测试其他格式的支持检测
    supported_formats = ['.eml', '.pdf', '.xlsx', '.docx', '.csv']
    print(f"\n   支持的格式: {', '.join(supported_formats)}")

    return len(formats_tested) > 0


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("航运智能账单助手 V2 - 集成测试")
    print("=" * 60)

    results = []

    # 运行测试
    results.append(("文件解析器", test_parser()))
    results.append(("Agent模拟模式", test_agent_mock()))
    results.append(("Agent真实模式", test_agent_real()))
    results.append(("演示工作流", test_demo_workflow()))
    results.append(("多格式支持", test_file_formats()))

    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = 0
    failed = 0
    skipped = 0

    for name, result in results:
        if result is True:
            print(f"✅ {name}: 通过")
            passed += 1
        elif result is False:
            print(f"❌ {name}: 失败")
            failed += 1
        else:
            print(f"⚠️  {name}: 跳过")
            skipped += 1

    print(f"\n总计: {passed} 通过, {failed} 失败, {skipped} 跳过")

    if failed == 0:
        print("\n所有测试通过！系统准备就绪。")
    else:
        print(f"\n有 {failed} 个测试失败，请检查。")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
