"""
完整演示脚本 - 展示系统端到端功能
无需配置 API，使用模拟数据
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from billing_agent.workflow import BillingWorkflow
from billing_agent.demo import DEMO_SCENARIOS
import json

def demo_full_workflow():
    """演示完整工作流"""

    print("=" * 70)
    print("航运智能账单助手 V2 - 完整演示")
    print("=" * 70)

    # 创建工作流
    workflow = BillingWorkflow(
        accounting_entity="Demo Origin",
        use_mock_data=True
    )

    # 演示所有4个场景
    scenarios = [
        ("update", "场景1: 明确更新"),
        ("ambiguous", "场景2: 同名费用歧义"),
        ("create", "场景3: 新增费用"),
        ("conditional", "场景4: 条件收费")
    ]

    for scenario_key, scenario_name in scenarios:
        print(f"\n{'=' * 70}")
        print(f"运行: {scenario_name}")
        print("=" * 70)

        try:
            # 处理场景
            results = workflow.process_demo_scenario(
                scenario_name=scenario_key,
                output_dir=Path("output") / scenario_key
            )

            # 显示摘要
            summary = results['summary']
            print(f"\n✅ 处理完成")
            print(f"   总决策数: {summary['total_decisions']}")
            print(f"   CREATE: {summary['operations']['CREATE']}")
            print(f"   UPDATE: {summary['operations']['UPDATE']}")
            print(f"   NO_CHANGE: {summary['operations']['NO_CHANGE']}")
            print(f"   PENDING_REVIEW: {summary['operations']['PENDING_REVIEW']}")
            print(f"   排除项: {summary['excluded_items']}")

            # 显示详细决策过程
            print(f"\n📋 决策详情:")
            for i, result in enumerate(results['processing_results'], 1):
                print(f"\n   费用 #{i}: {result['charge_details']['original_name']}")
                print(f"   ├─ 最终操作: {result['operation']}")
                print(f"   ├─ 模型建议: {result['model_suggestion']} (置信度: {result['model_confidence']})")
                print(f"   ├─ 模型理由: {result['model_reasoning']}")
                print(f"   ├─ 程序验证: {result['program_validation']}")
                if result['validation_issues']:
                    print(f"   ├─ 验证问题: {', '.join(result['validation_issues'])}")
                if result['conflict_resolution']:
                    print(f"   └─ 冲突解决: {result['conflict_resolution']}")

            # 保存结果
            output_file = Path("output") / scenario_key / "summary.txt"
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"{scenario_name}\n")
                f.write("=" * 70 + "\n\n")
                f.write(json.dumps(results, indent=2, ensure_ascii=False, default=str))

            print(f"\n💾 结果已保存到: {output_file.parent}")

        except Exception as e:
            print(f"\n❌ 处理失败: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print("演示完成！")
    print("=" * 70)
    print("\n查看详细结果:")
    print("  - output/update/       - 明确更新场景")
    print("  - output/ambiguous/    - 歧义场景")
    print("  - output/create/       - 新增场景")
    print("  - output/conditional/  - 条件收费场景")
    print("\n每个目录包含:")
    print("  - processing_results.json  - 详细处理结果")
    print("  - ledger_snapshot.json     - 账本快照")
    print("  - run_report.json          - 运行报告")
    print("  - summary.txt              - 文本摘要")


def demo_agent_decision():
    """演示 Agent 决策过程"""

    print("\n" + "=" * 70)
    print("Agent 决策过程演示")
    print("=" * 70)

    from billing_agent.demo import get_demo_scenario, get_demo_ledger

    # 获取演示数据
    scenario = get_demo_scenario("update")
    ledger = get_demo_ledger()

    print("\n📄 模拟材料内容:")
    print("   '请将提单号 BL-2024-001 的操作费从 50 美元改为 40 美元'")

    print("\n📚 旧账记录:")
    for record in ledger.records[:3]:
        print(f"   - {record.charge_details.original_name}: "
              f"{record.charge_details.amount} {record.charge_details.currency} "
              f"(ID: {record.record_id})")

    print("\n🤖 Agent 决策:")
    for decision in scenario.decisions:
        print(f"\n   费用: {decision.charge_details.original_name}")
        print(f"   ├─ 建议操作: {decision.suggested_operation}")
        print(f"   ├─ 置信度: {decision.confidence}")
        print(f"   ├─ 理由: {decision.operation_reasoning}")
        print(f"   └─ 匹配记录: {decision.matched_record_id or 'N/A'}")


def demo_validation():
    """演示验证和冲突解决"""

    print("\n" + "=" * 70)
    print("验证和冲突解决演示")
    print("=" * 70)

    from billing_agent.demo import get_demo_scenario, get_demo_ledger
    from billing_agent.validator import Validator
    from billing_agent.ledger import resolve_operation

    scenario = get_demo_scenario("ambiguous")
    ledger = get_demo_ledger()
    validator = Validator("Demo Origin")

    print("\n场景: 同名费用歧义")
    print("材料: '修改 HANDLING CHARGE 为 70 美元'")
    print("问题: 旧账中有两条 HANDLING CHARGE (65 和 35 美元)")

    for decision in scenario.decisions:
        print(f"\n🤖 模型决策:")
        print(f"   建议: {decision.suggested_operation}")
        print(f"   理由: {decision.operation_reasoning}")

        print(f"\n🔍 程序验证:")
        validation = validator.validate_decision(decision, ledger)
        print(f"   程序判断: {validation.program_operation}")
        print(f"   验证问题: {validation.validation_issues}")

        print(f"\n⚖️ 冲突解决:")
        final_op = resolve_operation(decision, validation, ledger)
        print(f"   最终操作: {final_op.operation}")
        print(f"   解决策略: {final_op.resolution_strategy}")
        print(f"   原因: {final_op.resolution_reason}")


if __name__ == "__main__":
    # 运行所有演示
    demo_full_workflow()
    demo_agent_decision()
    demo_validation()

    print("\n" + "=" * 70)
    print("所有演示完成！")
    print("=" * 70)
